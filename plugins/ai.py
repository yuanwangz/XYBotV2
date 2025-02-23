import asyncio
import base64
import imghdr
import io
import json
import tomllib
import traceback
from uuid import uuid4

import aiosqlite
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, MessagesState, StateGraph
from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from WechatAPI import WechatAPIClient
from database import BotDatabase
from utils.decorators import *
from utils.plugin_base import PluginBase


class GenerateImage(BaseModel):
    """Generate a image using AI. 用AI生成一个图片。"""
    prompt: str = Field(..., description="The prompt(or description) of image")


class Ai(PluginBase):
    description = "AI插件"
    author = "HenryXiaoYang"
    version = "1.0.0"
    
    priority: int = 10
    mutex_group: str = "text_response"

    def __init__(self):
        super().__init__()

        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        with open("main_config.toml", "rb") as f:
            main_config = tomllib.load(f)

        config = plugin_config["Ai"]
        openai_config = main_config["OpenAI"]

        # get all the command from other plugin
        self.other_command = []
        for plugin in plugin_config:
            if plugin != "Ai":
                self.other_command.extend(plugin_config[plugin].get("command", []))
        self.other_command.extend(
            ["加积分", "减积分", "设置积分", "添加白名单", "移除白名单", "白名单列表", "天气", "五子棋", "五子棋创建",
             "五子棋邀请", "邀请五子棋", "接受", "加入", "下棋", "加载插件", "加载所有插件", "卸载插件", "卸载所有插件",
             "重载插件", "重载所有插件", "插件列表"])

        main_config = main_config["XYBot"]

        # 读取 [Ai] 设置
        self.enable = config["enable"]

        self.ai_db_url = config["database-url"]

        self.enable_command = config["enable-command"]
        self.enable_at = config["enable-at"]
        self.enable_private = config["enable-private"]

        self.command = config["command"]

        # 读取 [Ai.MainModel] 设置
        config = plugin_config["Ai"]["MainModel"]
        self.base_url = config["base-url"] if config["base-url"] else openai_config["base-url"]
        self.api_key = config["api-key"] if config["api-key"] else openai_config["api-key"]

        self.model_name = config["model-name"]

        self.text_input = config["text-input"]
        self.image_input = config["image-input"]
        self.image_formats = config["image-formats"]
        self.voice_input = config["voice-input"]

        if self.voice_input not in ["None", "Native", "NonNative"]:
            logger.error("AI插件设置错误：voice-input 必须为 None 或者 Native 或者 NonNative")

        self.text_output = config["text-output"]
        self.image_output = config["image-output"]
        self.voice_output = config["voice-output"]

        if self.voice_output not in ["None", "Native", "NonNative"]:
            logger.error("AI插件设置错误：voice-output 必须为 None 或者 Native 或者 NonNative")

        self.temperature = config["temperature"]
        self.max_history_messages = config["max-history-messages"]
        self.model_kwargs = config["model_kwargs"]

        self.prompt = config["prompt"]

        modalities = []
        if self.text_output:
            modalities.append("text")
        if self.image_output:
            modalities.append("image")
        if self.voice_output == "Native":
            modalities.append("audio")
            if not self.model_kwargs.get("audio", None):
                self.model_kwargs["audio"] = {}
            self.model_kwargs["audio"]["format"] = "wav"

        self.model_kwargs["modalities"] = modalities

        # 读取[Ai.Point]设置
        config = plugin_config["Ai"]["Point"]
        self.point_mode = config["mode"]

        if self.point_mode not in ["None", "Together"]:
            logger.error("AI插件设置错误：point-mode 必须为 None 或者 Together")

        self.together_price = config["price"]

        self.admin_ignore = config["admin-ignore"]
        self.whitelist_ignore = config["whitelist-ignore"]

        # 读取 [Ai.GenerateImage] 设置
        config = plugin_config["Ai"]["GenerateImage"]
        self.image_base_url = config["base-url"] if config["base-url"] else openai_config["base-url"]
        self.image_api_key = config["api-key"] if config["api-key"] else openai_config["api-key"]
        self.image_model_name = config["model-name"]
        self.image_size = config["size"]
        self.image_additional_param = config["additional-param"]

        if self.image_output:
            self.prompt += config["add-prompt"]

        # 读取 [Ai.SpeechToText] 设置
        config = plugin_config["Ai"]["SpeechToText"]
        self.speech2text_base_url = config["base-url"] if config["base-url"] else openai_config["base-url"]
        self.speech2text_api_key = config["api-key"] if config["api-key"] else openai_config["api-key"]
        self.speech2text_model_name = config["model-name"]

        # 读取 [Ai.TextToSpeech] 设置
        config = plugin_config["Ai"]["TextToSpeech"]
        self.text2speech_base_url = config["base-url"] if config["base-url"] else openai_config["base-url"]
        self.text2speech_api_key = config["api-key"] if config["api-key"] else openai_config["api-key"]
        self.text2speech_model_name = config["model-name"]
        self.text2speech_voice = config["voice"]
        self.text2speech_speed = config["speed"]
        self.text2speech_additional_param = config["additional-param"]

        # 读取主设置
        self.admins = main_config["admins"]

        # 初始化langchain
        self.llm = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model_name,
            temperature=self.temperature,
            model_kwargs=self.model_kwargs
        )

        # tool-call
        if self.image_output:
            tools = [GenerateImage]
            self.llm = self.llm.bind_tools(tools)

        # 初始化机器人数据库
        self.db = BotDatabase()

        # 准备异步初始化
        self.sqlite_conn = None
        self.sqlite_saver = None
        self.ai = None

        self.inited = False

    async def async_init(self):
        try:
            if self.sqlite_conn:
                try:
                    async with self.sqlite_conn.cursor() as cursor:
                        await cursor.execute("SELECT 1")
                    return  # 如果查询成功，说明连接有效，直接返回
                except Exception:
                    # 如果查询失败，说明连接无效，需要重新初始化
                    if self.sqlite_conn:
                        await self.sqlite_conn.close()

            # 创建新连接和初始化
            self.sqlite_conn = await aiosqlite.connect(self.ai_db_url)
            self.sqlite_saver = AsyncSqliteSaver(self.sqlite_conn)

            workflow = StateGraph(state_schema=MessagesState)
            workflow.add_edge(START, "model")
            workflow.add_node("model", self.call_model)

            self.ai = workflow.compile(checkpointer=self.sqlite_saver)

            self.inited = True

            logger.info("AI插件数据库初始化完毕")
        except Exception as e:
            logger.error(f"数据库初始化失败: {str(e)}")
            raise

    def __del__(self):
        """确保资源被正确释放"""
        try:
            if hasattr(self, 'sqlite_conn') and self.sqlite_conn:
                asyncio.run(self.sqlite_conn.close())
        except Exception as e:
            logger.error(f"关闭数据库连接时出错: {str(e)}")

    async def call_model(self, state: MessagesState):
        """处理所有类型的消息"""
        messages = state["messages"]

        # 限制历史消息数量
        if len(messages) > self.max_history_messages:
            # 保留系统提示(第一条)和最近的消息
            messages = [messages[0]] + messages[-self.max_history_messages + 1:]
            state["messages"] = messages  # 更新状态中的消息列表

        try:
            response = await self.llm.ainvoke(messages)
            return {"messages": response}
        except Exception as e:
            logger.error(f"模型调用出错: {str(e)}")
            raise

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        if not self.text_input:
            return

        await self.async_init()

        content = str(message["Content"]).strip()
        command = content.split(" ")

        is_command = command[0] in self.command and self.enable_command
        is_private = not message["IsGroup"] and self.enable_private
        if not is_command and not is_private:
            return
        elif command[0] in self.other_command:
            return

        for c in ["清除历史记录", "清除记录", "清除历史", "清除对话"]:
            if c in message["Content"]:
                return await self.delete_user_thread_id(bot, message)
        for c in ["清除所有人历史记录", "清除所有历史记录", "清除所有记录", "清除所有人记录", "清除所有人对话"]:
            if c in message["Content"]:
                if message["SenderWxid"] not in self.admins:
                    await bot.send_at_message(
                        message["FromWxid"],
                        f"\n-----Bot-----\n😠你没有这样做的权限！",
                        [message["SenderWxid"]]
                    )
                    return

                result = await self.delete_all_user_thread_id()
                if result:
                    await bot.send_at_message(
                        message["FromWxid"],
                        f"\n-----Bot-----\n🗑️清除成功✅",
                        [message["SenderWxid"]]
                    )
                else:
                    await bot.send_at_message(
                        message["FromWxid"],
                        f"\n-----Bot-----\n清除失败，请查看日志",
                        [message["SenderWxid"]]
                    )

                return

        if message["IsGroup"]:
            message["Content"] = content[len(command[0]):].strip()

        if await self.check_point(bot, message):
            await self.get_ai_response(bot, message)

    @on_at_message
    async def handle_at(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        if not self.text_input:
            return

        await self.async_init()

        message["Content"] = str(message["Content"]).replace(f"@{bot.nickname}\u2005", "").strip()

        if await self.check_point(bot, message):
            await self.get_ai_response(bot, message)

    @on_voice_message
    async def handle_voice(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        if message["IsGroup"]:
            return

        if not self.voice_input:
            return

        await self.async_init()

        if await self.check_point(bot, message):
            await self.get_ai_response(bot, message)

    @on_image_message
    async def handle_image(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        if message["IsGroup"]:
            return

        if not self.image_input:
            return

        await self.async_init()

        if await self.check_point(bot, message):
            await self.get_ai_response(bot, message)
    
    @on_quote_message
    async def handle_quote(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return
        
        if not self.text_input:
            return
        
        if not message["Quote"]:
            return
        if message["IsGroup"] and not message.get("is_at", False):
            return
        await self.async_init()
        
        message["Content"] = str(message["Content"]).replace(f"@{bot.nickname}\u2005", "").strip()
        
        if await self.check_point(bot, message):
            await self.get_ai_response(bot, message)

    @schedule('cron', hour=5)
    async def reset_chat_history(self, _):
        await self.async_init()

        r = await self.delete_all_user_thread_id()
        if r:
            logger.success("数据库：清除AI上下文成功")
        else:
            logger.error("数据库：清除AI上下文失败")

    async def get_ai_response(self, bot: WechatAPIClient, message: dict):
        from_wxid = message["FromWxid"]
        sender_wxid = message["SenderWxid"]
        user_input = message["Content"]
        is_group = message["IsGroup"]
        is_quote = message.get("Quote", None)
        
        if not user_input:
            await bot.send_at_message(from_wxid, "\n-----Bot-----\n你还没输入呀！🤔", [sender_wxid] if is_group else [])
            return
        
        if is_quote:
            quote_input = is_quote["Content"]
            if is_quote["MsgType"] == 1:
                user_input = f"[引用信息：{quote_input}];{user_input}"
            elif is_quote["MsgType"] == 3:
                image_format = self.get_img_format(quote_input)
                user_input = [
                        {"type": "text", "text": user_input},
                        {"type": "image_url", "image_url": {"url": f"data:image/{image_format};base64,{quote_input}"}},
                    ]
            elif is_quote["MsgType"] == 6:
                mime_type = self.get_mime_type(is_quote["Filename"])
                user_input = [
                        {"type": "text", "text": user_input},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{quote_input}"}},
                    ]

        try:
            # 上下文
            thread_id = self.db.get_llm_thread_id(sender_wxid if not is_group else from_wxid, self.model_name)
            history_flag = True
            if not thread_id:
                thread_id = str(uuid4())
                history_flag = False
                self.db.save_llm_thread_id(sender_wxid if not is_group else from_wxid, thread_id, self.model_name)
            configurable = {
                "configurable": {
                    "thread_id": thread_id,
                }
            }

            # 消息类型
            if (message["MsgType"] == 1 or message["MsgType"] == 49) and self.text_input:  # 文本输入
                input_message = (
                    [SystemMessage(content=self.prompt)] if not history_flag else []
                ) + [HumanMessage(content=user_input)]

            elif message["MsgType"] == 3 and self.image_input:  # 图片输入
                image_base64 = user_input

                image_format = self.get_img_format(image_base64)
                # 检查图片格式
                if image_format not in self.image_formats:
                    await bot.send_at_message(
                        from_wxid,
                        f"-----Bot-----\n⚠️不支持该图片格式！支持: {self.image_formats}",
                        [sender_wxid]
                    )
                    return None
                input_message = (
                    [SystemMessage(content=self.prompt)] if not history_flag else []
                ) + [HumanMessage(content=[
                        {"type": "image_url", "image_url": {"url": f"data:image/{image_format};base64,{image_base64}"}},
                    ])
                ]

            elif message["MsgType"] == 34 and self.voice_input != "None":  # 语音输入
                if self.voice_input == "Native":
                    wav_base64 = bot.byte_to_base64(user_input)
                    input_message = (
                    [SystemMessage(content=self.prompt)] if not history_flag else []
                ) + [HumanMessage(content=[
                            {"type": "input_audio", "input_audio": {"data": wav_base64, "format": "wav"}},
                        ])
                    ]
                else:
                    text_input = await self.get_text_from_voice(user_input)
                    input_message = (
                    [SystemMessage(content=self.prompt)] if not history_flag else []
                ) + [HumanMessage(content=text_input)
                    ]

            else:
                raise ValueError("未知的输入格式！")

            # 请求API
            logger.debug("请求AI的API, thread id: {}", thread_id)
            output = await self.ai.ainvoke({"messages": input_message}, configurable)
            last_message = output["messages"][-1]
            # 什么类型输入，什么类型输出
            if message["MsgType"] == 1 and self.text_output:  # 文本输出
                if self.voice_output == "Native":
                    output = last_message.additional_kwargs['audio']['transcript']
                else:
                    output = last_message.content

                if output:
                    await bot.send_at_message(from_wxid, "\n" + output, [sender_wxid] if is_group else [])

            elif message["MsgType"] == 3 and self.image_output:  # 图片输出
                if self.voice_output == "Native":
                    output = last_message.additional_kwargs['audio']['transcript']
                else:
                    output = last_message.content

                if output:
                    await bot.send_at_message(from_wxid, "\n" + output, [sender_wxid] if is_group else [])

            elif message["MsgType"] == 34 and self.voice_output != "None":  # 语音输出
                if self.voice_output == "Native":  # 原生支持
                    if "audio" in last_message.additional_kwargs:
                        await bot.send_voice_message(from_wxid,
                                                     voice_base64=last_message.additional_kwargs['audio']['data'],
                                                     format="wav")
                    elif last_message.content:  # 无语音，有文本
                        await bot.send_at_message(from_wxid, "\n" + last_message.content, [sender_wxid] if is_group else [])
                else:  # 非原生
                    audio_byte = await self.get_voice_from_text(last_message.content)
                    audio_base64 = bot.byte_to_base64(audio_byte)
                    await bot.send_voice_message(from_wxid,
                                                 voice_base64=audio_base64,
                                                 format="wav")
            else:  # fallback
                await bot.send_at_message(from_wxid, "\n" + last_message.content, [sender_wxid] if is_group else [])

            # 检查是否有图片生成tool call
            if last_message.additional_kwargs.get("tool_calls"):
                for tool_call in last_message.additional_kwargs["tool_calls"]:
                    if tool_call["function"]["name"] == "GenerateImage":
                        await bot.send_at_message(from_wxid, f"\n🖼️正在生成图片...", [sender_wxid] if is_group else [])
                        try:
                            prompt = json.loads(tool_call["function"]["arguments"])["prompt"]
                            b64_list = await self.generate_image(prompt)
                            for img_b64 in b64_list:
                                await bot.send_image_message(from_wxid, image_base64=img_b64)
                        except Exception as e:
                            logger.error(f"生成图片失败: {traceback.format_exc()}")
                            await bot.send_at_message(from_wxid, f"\n生成图片失败: {str(e)}", [sender_wxid] if is_group else [])

        except Exception as e:
            await bot.send_at_message(
                from_wxid,
                f"-----Bot-----\n❌请求失败：{str(e)}",
                [sender_wxid]
            )
            logger.error(traceback.format_exc())

    async def generate_image(self, prompt: str) -> list:
        client = AsyncOpenAI(
            base_url=self.image_base_url,
            api_key=self.image_api_key
        )

        try:
            resp = await client.images.generate(
                model=self.image_model_name,
                prompt=prompt,
                size=self.image_size,
                n=1,
                extra_body=self.image_additional_param
            )
            b64_list = []
            for item in resp.data:
                b64_list.append(item.url)
            return b64_list
        except:
            logger.error(traceback.format_exc())
            raise

    async def get_text_from_voice(self, user_input: bytes):
        tempfile = io.BytesIO(user_input)
        tempfile.name = "audio.wav"
        client = AsyncOpenAI(
            base_url=self.speech2text_base_url,
            api_key=self.speech2text_api_key
        )
        try:
            resp = await client.audio.transcriptions.create(
                model=self.speech2text_model_name,
                file=tempfile
            )
            return resp.text
        except:
            logger.error(traceback.format_exc())
            raise

    async def get_voice_from_text(self, text: str) -> bytes:
        client = AsyncOpenAI(
            base_url=self.text2speech_base_url,
            api_key=self.text2speech_api_key
        )
        try:
            resp = await client.audio.speech.create(
                model=self.text2speech_model_name,
                response_format="wav",
                voice=self.text2speech_voice,
                speed=float(self.text2speech_speed),
                # extra_body=self.text2speech_additional_param,
                input=text,
            )
            return resp.content
        except:
            logger.error(traceback.format_exc())
            raise

    @staticmethod
    def get_img_format(img_base64: str) -> str:
        if ',' in img_base64:
            img_base64 = img_base64.split(',')[1]
        return imghdr.what(io.BytesIO(base64.b64decode(img_base64)))  # Python特有的用单行嵌套来加速性能

    @staticmethod
    def get_mime_type(file_name: str) -> str:
        """Get MIME type from file extension or data"""
        mime_map = {
            'txt': 'text/plain',
            'pdf': 'application/pdf', 
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'png': 'image/png',
            'jpg': 'image/jpeg', 
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        file_ext = file_name.split('.')[-1].lower() if '.' in file_name else ''
        return mime_map.get(file_ext, 'application/octet-stream')
    
    async def delete_user_thread_id(self, bot: WechatAPIClient, message: dict):
        thread_id_dict = dict(self.db.get_llm_thread_id(message["SenderWxid"]))
        cursor = await self.sqlite_conn.cursor()
        try:
            for value in thread_id_dict.values():
                await cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (value,))
                await cursor.execute("DELETE FROM writes WHERE thread_id = ?", (value,))
            await self.sqlite_conn.commit()
        except Exception as e:
            await bot.send_at_message(
                message["FromWxid"],
                f"-----Bot-----\n❌删除失败：{str(e)}",
                [message["SenderWxid"]]
            )
            logger.error(traceback.format_exc())
            return
        finally:
            cursor.close()

        self.db.save_llm_thread_id(message["SenderWxid"], "", self.model_name)
        await bot.send_at_message(
            message["FromWxid"],
            f"\n-----Bot-----\n🗑️清除成功✅",
            [message["SenderWxid"]]
        )
        return

    async def delete_all_user_thread_id(self) -> bool:
        logger.debug(self.db)
        self.db.delete_all_llm_thread_id()

        cursor = await self.sqlite_conn.cursor()
        try:
            await cursor.execute("DELETE FROM checkpoints")
            await cursor.execute("DELETE FROM writes")
            await self.sqlite_conn.commit()

            # 关闭当前连接
            await cursor.close()
            await self.sqlite_conn.close()

            # 重新建立连接并执行 VACUUM
            self.sqlite_conn = await aiosqlite.connect(self.ai_db_url)
            cursor = await self.sqlite_conn.cursor()
            await cursor.execute("VACUUM")

            # 重新初始化 sqlite_saver
            self.sqlite_saver = AsyncSqliteSaver(self.sqlite_conn)

        except Exception as e:
            logger.error(traceback.format_exc())
            return False
        finally:
            await cursor.close()

        return True

    async def check_point(self, bot: WechatAPIClient, message: dict) -> bool:
        wxid = message["SenderWxid"]

        if self.point_mode == "None":
            return True

        elif self.point_mode == "Together":
            if wxid in self.admins and self.admin_ignore:
                return True
            elif self.db.get_whitelist(wxid) and self.whitelist_ignore:
                return True
            else:
                if self.db.get_points(wxid) < self.together_price:
                    await bot.send_at_message(message["FromWxid"],
                                              f"\n-----Bot-----\n"
                                              f"😭你的积分不够啦！需要 {self.together_price} 积分",
                                              [wxid])
                    return False

                self.db.add_points(wxid, -self.together_price)
                return True

        else:
            return True
