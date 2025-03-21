import asyncio
import base64
import imghdr
import io
import json
import tomllib
import traceback
import time
from uuid import uuid4
from datetime import datetime 

import aiosqlite
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, MessagesState, StateGraph
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
import re

# 定义工具模型
class GenerateImage(BaseModel):
    """Generate a image using AI. 用AI生成一个图片。"""
    prompt: str = Field(..., description="The prompt(or description) of image")

class InternetAccess(BaseModel):
    """Access the internet to search for real-time information and answer queries."""
    query: str = Field(..., description="The query keywords for internet search engine")

class AIChatTester:
    def __init__(self, config_path="plugins/all_in_one_config.toml", main_config_path="main_config.toml"):
        # 加载配置
        with open(config_path, "rb") as f:
            plugin_config = tomllib.load(f)

        with open(main_config_path, "rb") as f:
            main_config = tomllib.load(f)

        config = plugin_config["Ai"]
        openai_config = main_config["OpenAI"]

        # 读取 [Ai.MainModel] 设置
        model_config = plugin_config["Ai"]["MainModel"]
        self.base_url = model_config["base-url"] if model_config["base-url"] else openai_config["base-url"]
        self.api_key = model_config["api-key"] if model_config["api-key"] else openai_config["api-key"]

        self.model_name = model_config["model-name"]
        self.temperature = model_config["temperature"]
        self.max_history_messages = model_config["max-history-messages"]
        self.model_kwargs = model_config["model_kwargs"]
        self.prompt = model_config["prompt"]

        # 设置模态性
        modalities = []
        if model_config["text-output"]:
            modalities.append("text")
        if model_config["image-output"]:
            modalities.append("image")
        if model_config["voice-output"] == "Native":
            modalities.append("audio")
            if not self.model_kwargs.get("audio", None):
                self.model_kwargs["audio"] = {}
            self.model_kwargs["audio"]["format"] = "wav"

        self.model_kwargs["modalities"] = modalities

        # 图片生成配置
        image_config = plugin_config["Ai"]["GenerateImage"]
        self.image_base_url = image_config["base-url"] if image_config["base-url"] else openai_config["base-url"]
        self.image_api_key = image_config["api-key"] if image_config["api-key"] else openai_config["api-key"]
        self.image_output_type = image_config["image-output-type"]
        self.image_model_name = image_config["model-name"]
        self.image_size = image_config["size"]
        self.image_additional_param = image_config["additional-param"]
        
        # 互联网访问配置
        internet_config = plugin_config["Ai"]["InternetAccess"]
        self.internet_access_base_url = internet_config["base-url"] if internet_config["base-url"] else openai_config["base-url"]
        self.internet_access_api_key = internet_config["api-key"] if internet_config["api-key"] else openai_config["api-key"]
        self.internet_access_model_name = internet_config["model-name"]
        
        # 语音转换配置
        speech2text_config = plugin_config["Ai"]["SpeechToText"]
        self.speech2text_base_url = speech2text_config["base-url"] if speech2text_config["base-url"] else openai_config["base-url"]
        self.speech2text_api_key = speech2text_config["api-key"] if speech2text_config["api-key"] else openai_config["api-key"]
        self.speech2text_model_name = speech2text_config["model-name"]
        
        text2speech_config = plugin_config["Ai"]["TextToSpeech"]
        self.text2speech_base_url = text2speech_config["base-url"] if text2speech_config["base-url"] else openai_config["base-url"]
        self.text2speech_api_key = text2speech_config["api-key"] if text2speech_config["api-key"] else openai_config["api-key"]
        self.text2speech_model_name = text2speech_config["model-name"]
        self.text2speech_voice = text2speech_config["voice"]
        self.text2speech_speed = text2speech_config["speed"]
        self.text2speech_additional_param = text2speech_config["additional-param"]

        # 初始化 langchain
        self.llm = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model_name,
            temperature=self.temperature,
            model_kwargs=self.model_kwargs
        )

        # 工具绑定
        tools = []
        if "image" in modalities:
            tools.append(GenerateImage)
        if model_config["internet-access"]:
            tools.append(InternetAccess)
        
        if tools:
            self.llm = self.llm.bind_tools(tools)

        self.sqlite_conn = None
        self.sqlite_saver = None
        self.ai = None
        self.thread_id = None
        self.inited = False

    async def async_init(self):
        try:
            if self.sqlite_conn:
                await self.sqlite_conn.close()
            
            # 使用内存数据库用于测试
            self.sqlite_conn = await aiosqlite.connect(":memory:")
            self.sqlite_saver = AsyncSqliteSaver(self.sqlite_conn)

            workflow = StateGraph(state_schema=MessagesState)
            workflow.add_edge(START, "model")
            workflow.add_node("model", self.call_model)

            self.ai = workflow.compile(checkpointer=self.sqlite_saver)
            self.thread_id = str(uuid4())
            self.inited = True
            print("AI测试器初始化完毕")
        except Exception as e:
            print(f"初始化失败: {str(e)}")
            raise

    async def call_model(self, state: MessagesState):
        """处理所有类型的消息"""
        start_time = time.time()
        messages = state["messages"]

        # 限制历史消息数量
        if len(messages) > self.max_history_messages:
            # 保留系统提示(第一条)和最近的消息
            messages = [messages[0]] + messages[-self.max_history_messages + 1:]
            state["messages"] = messages  # 更新状态中的消息列表

        try:
            response = await self.llm.ainvoke(messages)
            end_time = time.time()
            print(f"模型调用耗时: {end_time - start_time:.2f}秒")
            return {"messages": response}
        except Exception as e:
            print(f"模型调用出错: {str(e)}")
            raise

    async def process_message(self, user_input, message_type="text", image_data=None, voice_data=None):
        """处理消息并获取AI响应"""
        total_start_time = time.time()
        
        if not self.inited:
            await self.async_init()

        try:
            # 配置线程ID
            configurable = {
                "configurable": {
                    "thread_id": self.thread_id,
                }
            }

            # 根据消息类型构建输入
            if message_type == "text":
                input_message = [SystemMessage(content=self.prompt)]
                input_message.append(HumanMessage(content=user_input))
            
            elif message_type == "image" and image_data:
                image_base64 = image_data
                image_format = self.get_img_format(image_base64)
                input_message = [SystemMessage(content=self.prompt)]
                input_message.append(HumanMessage(content=[
                    {"type": "image_url", "image_url": {"url": f"data:image/{image_format};base64,{image_base64}"}},
                    {"type": "text", "text": user_input or "详细描述图片内容有什么"},
                ]))
            
            elif message_type == "voice" and voice_data:
                voice_start_time = time.time()
                input_message = [SystemMessage(content=self.prompt)]
                # 使用模型原生支持语音输入
                if "audio" in self.model_kwargs.get("modalities", []):
                    wav_base64 = self.byte_to_base64(voice_data)
                    input_message.append(HumanMessage(content=[
                        {"type": "input_audio", "input_audio": {"data": wav_base64, "format": "wav"}},
                    ]))
                else:
                    # 语音转文本处理
                    text_input = await self.get_text_from_voice(voice_data)
                    input_message.append(HumanMessage(content=text_input))
                voice_end_time = time.time()
                print(f"语音处理耗时: {voice_end_time - voice_start_time:.2f}秒")
            else:
                raise ValueError(f"未支持的消息类型: {message_type}")

            # 请求AI API
            print(f"请求AI API, thread id: {self.thread_id}")
            model_start_time = time.time()
            output = await self.ai.ainvoke({"messages": input_message}, configurable)
            model_end_time = time.time()
            print(f"AI主模型响应耗时: {model_end_time - model_start_time:.2f}秒")
            
            # 处理AI响应
            old_output = output
            last_message = output["messages"][-1]
            
            # 获取文本响应
            if "audio" in last_message.additional_kwargs:
                text_response = last_message.additional_kwargs['audio']['transcript']
            else:
                text_response = last_message.content
            
            print(f"\nAI回复: {text_response}")
            
            # 检查工具调用
            tool_calls_time = 0
            if last_message.additional_kwargs.get("tool_calls"):
                tool_start_time = time.time()
                for tool_call in last_message.additional_kwargs["tool_calls"]:
                    if tool_call["function"]["name"] == "GenerateImage":
                        print("\n🖼️正在生成图片...")
                        image_start_time = time.time()
                        try:
                            prompt = json.loads(tool_call["function"]["arguments"])["prompt"]
                            b64_list, generate_image_result = await self.generate_image(prompt, old_output)
                            
                            tool_message_content = ""
                            if generate_image_result:
                                tool_message_content = generate_image_result
                                print(f"\n生成图片结果: {generate_image_result}")
                            else:
                                image_links = []
                                for i, img_url in enumerate(b64_list):
                                    image_links.append(f"图片{i+1}: {img_url[:30]}...{img_url[-10:]}")
                                tool_message_content = "已生成如下图片：\n" + "\n".join(image_links)
                                print(f"\n图片已生成，共{len(b64_list)}张")
                            
                            image_end_time = time.time()
                            print(f"图片生成耗时: {image_end_time - image_start_time:.2f}秒")
                            
                            # 处理工具回调
                            callback_start_time = time.time()
                            tool_message = ToolMessage(
                                tool_call_id=tool_call["id"],
                                # tool_call_id="GenerateImage",
                                content=tool_message_content,
                                name="GenerateImage",
                                additional_kwargs={"name": "GenerateImage"}
                            )
                            output = await self.ai.ainvoke({"messages": [tool_message]}, configurable)
                            last_message = output["messages"][-1]
                            callback_end_time = time.time()
                            print(f"图片处理回调耗时: {callback_end_time - callback_start_time:.2f}秒")
                            print(f"\nAI对图片的回复: {last_message.content}")
                            
                        except Exception as e:
                            print(f"生成图片失败: {str(e)}")
                            traceback.print_exc()
                    
                    elif tool_call["function"]["name"] == "InternetAccess":
                        print("\n🔍正在搜索互联网...")
                        search_start_time = time.time()
                        try:
                            prompt = json.loads(tool_call["function"]["arguments"])["query"]
                            search_result = await self.internet_access(old_output, prompt)
                            search_end_time = time.time()
                            print(f"互联网搜索耗时: {search_end_time - search_start_time:.2f}秒")
                            print(f"\n搜索结果: {search_result}")
                            
                            callback_start_time = time.time()
                            tool_message = ToolMessage(
                                tool_call_id=tool_call["id"],
                                content=search_result,
                                name="InternetAccess"
                            )
                            output = await self.ai.ainvoke({"messages": [tool_message]}, configurable)
                            last_message = output["messages"][-1]
                            callback_end_time = time.time()
                            print(f"搜索结果处理回调耗时: {callback_end_time - callback_start_time:.2f}秒")
                            print(f"\nAI对搜索结果的回复: {last_message.content}")
                            
                        except Exception as e:
                            print(f"互联网访问失败: {str(e)}")
                            traceback.print_exc()
                
                tool_end_time = time.time()
                tool_calls_time = tool_end_time - tool_start_time
                print(f"工具调用总耗时: {tool_calls_time:.2f}秒")
            
            total_end_time = time.time()
            total_time = total_end_time - total_start_time
            print(f"\n总耗时: {total_time:.2f}秒")
            
            # 如果有工具调用，计算工具调用占总时间的百分比
            if tool_calls_time > 0:
                tool_percentage = (tool_calls_time / total_time) * 100
                print(f"工具调用占总时间的 {tool_percentage:.1f}%")
            
            return output
            
        except Exception as e:
            total_end_time = time.time()
            print(f"处理消息失败: {str(e)}")
            print(f"总耗时: {total_end_time - total_start_time:.2f}秒")
            traceback.print_exc()
            return None

    async def generate_image(self, prompt: str, input_message: dict) -> tuple:
        """生成图片"""
        start_time = time.time()
        client = AsyncOpenAI(
            base_url=self.image_base_url,
            api_key=self.image_api_key
        )

        try:
            b64_list = []
            chat_completion_resp = None
            if self.image_output_type == "imageGenerate":
                resp = await client.images.generate(
                    model=self.image_model_name,
                    prompt=prompt,
                    size=self.image_size,
                    n=1,
                    extra_body=self.image_additional_param
                )
                
                for item in resp.data:
                    b64_list.append(item.url)

            elif self.image_output_type == "chatCompletion":
                openai_messages = []
                openai_messages.append({"role": "system", "content": "你是一个资深绘画大师，没有谁比你更专业。规则：1、根据用户的要求，生成图片或修图。2、对于修图需要保持原图的风格不变。3、你必须在本轮对话中给出图片,即使用户没有提供具体的需求。4、绝不允许编造不存在的图片。你必须遵守这些规则，否则你将失去你的工作。"})
                for msg in input_message["messages"]:
                    if isinstance(msg, HumanMessage):
                        openai_messages.append({"role": "user", "content": msg.content})
                    elif isinstance(msg, AIMessage) and msg.content:
                        msg.tool_calls = []
                        openai_messages.append({"role": "assistant", "content": msg.content})
                    # elif isinstance(msg, ToolMessage) and msg.content:
                    #     openai_messages.append({"role": "tool", "content": msg.content})

                resp = await client.chat.completions.create(
                    model=self.image_model_name,
                    messages=openai_messages,
                    stream=False,
                )
                chat_completion_resp = resp.choices[0].message.content
                # 提取所有图片URL
                IMAGE_URL_PATTERN = r'\[image\]\((.*?)\)'
                img_urls = re.findall(IMAGE_URL_PATTERN, chat_completion_resp)
                for img_url in img_urls:
                    b64_list.append(img_url)

            end_time = time.time()
            print(f"图片生成API请求耗时: {end_time - start_time:.2f}秒")
            return b64_list, chat_completion_resp
            
        except Exception as e:
            end_time = time.time()
            print(f"生成图片错误: {str(e)}")
            print(f"失败耗时: {end_time - start_time:.2f}秒")
            traceback.print_exc()
            raise
    
    async def internet_access(self, input_message: dict, query: str) -> str:
        """互联网访问"""
        start_time = time.time()
        client = AsyncOpenAI(
            base_url=self.internet_access_base_url,
            api_key=self.internet_access_api_key
        )
        try:
            # Convert langchain messages to OpenAI format
            openai_messages = []
            openai_messages.append({"role": "system", "content": "现在时间是：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "，你是一个网络实时信息搜索工具，你根据用户的问题，使用联网搜索能力搜索相关信息，并总结返回搜索结果,要求简明扼要，排版整齐。"})
            for msg in input_message["messages"]:
                if isinstance(msg, HumanMessage):
                    openai_messages.append({"role": "user", "content": msg.content})
                elif isinstance(msg, AIMessage) and msg.content:
                    openai_messages.append({"role": "assistant", "content": msg.content})
            
            # 将最后一个消息替换为查询内容
            if openai_messages and openai_messages[-1]["role"] == "user":
                openai_messages[-1]["content"] = query
            else:
                openai_messages.append({"role": "user", "content": query})
            
            resp = await client.chat.completions.create(
                model=self.internet_access_model_name,
                messages=openai_messages,
                stream=False,
            )
            end_time = time.time()
            print(f"互联网访问API请求耗时: {end_time - start_time:.2f}秒")
            return resp.choices[0].message.content
        except Exception as e:
            end_time = time.time()
            print(f"互联网访问错误: {str(e)}")
            print(f"失败耗时: {end_time - start_time:.2f}秒")
            traceback.print_exc()
            raise

    async def get_text_from_voice(self, voice_data: bytes) -> str:
        """语音转文本"""
        start_time = time.time()
        tempfile = io.BytesIO(voice_data)
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
            end_time = time.time()
            print(f"语音转文本API请求耗时: {end_time - start_time:.2f}秒")
            return resp.text
        except Exception as e:
            end_time = time.time()
            print(f"语音转文本错误: {str(e)}")
            print(f"失败耗时: {end_time - start_time:.2f}秒")
            traceback.print_exc()
            raise

    async def get_voice_from_text(self, text: str) -> bytes:
        """文本转语音"""
        start_time = time.time()
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
                input=text,
            )
            end_time = time.time()
            print(f"文本转语音API请求耗时: {end_time - start_time:.2f}秒")
            return resp.content
        except Exception as e:
            end_time = time.time()
            print(f"文本转语音错误: {str(e)}")
            print(f"失败耗时: {end_time - start_time:.2f}秒")
            traceback.print_exc()
            raise

    @staticmethod
    def get_img_format(img_base64: str) -> str:
        """获取图片格式"""
        if ',' in img_base64:
            img_base64 = img_base64.split(',')[1]
        return imghdr.what(io.BytesIO(base64.b64decode(img_base64)))

    @staticmethod
    def byte_to_base64(data: bytes) -> str:
        """字节转base64"""
        return base64.b64encode(data).decode('utf-8')
        
    async def reset_conversation(self):
        """重置对话"""
        self.thread_id = str(uuid4())
        print(f"对话已重置，新线程ID: {self.thread_id}")


async def main():
    # 创建AI测试器实例
    start_time = time.time()
    ai_tester = AIChatTester()
    await ai_tester.async_init()
    init_time = time.time() - start_time
    print(f"初始化耗时: {init_time:.2f}秒")
    
    print("欢迎使用AI对话测试器!")
    print("输入 'exit' 退出")
    print("输入 'reset' 重置对话")
    print("输入 'image:URL' 测试图片输入 (例如 'image:https://example.com/image.jpg')")
    
    while True:
        user_input = input("\n请输入: ")
        
        if user_input.lower() == 'exit':
            break
        elif user_input.lower() == 'reset':
            await ai_tester.reset_conversation()
            continue
        elif user_input.lower().startswith('image:'):
            # 这里可以实现图片输入的处理
            # 为了简化，图片URL后面的部分作为文本输入
            image_url = user_input[6:].strip()
            print(f"图片输入暂未实现，图片URL: {image_url}")
            continue
            
        await ai_tester.process_message(user_input)
        
if __name__ == "__main__":
    asyncio.run(main()) 