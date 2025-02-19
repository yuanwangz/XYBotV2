import asyncio
import base64
from asyncio import Future
from asyncio import Queue, sleep
from io import BytesIO

import aiohttp
import moviepy as mp
import pysilk
from loguru import logger
from pydub import AudioSegment

from .base import *
from .protect import protector
from ..errors import *
import re


class MessageMixin(WechatAPIClientBase):
    def __init__(self, ip: str, port: int):
        # 初始化消息队列
        super().__init__(ip, port)
        self._message_queue = Queue()
        self._is_processing = False

    async def _process_message_queue(self):
        """
        处理消息队列的异步方法
        """
        if self._is_processing:
            return

        self._is_processing = True
        while True:
            if self._message_queue.empty():
                self._is_processing = False
                break

            func, args, kwargs, future = await self._message_queue.get()
            try:
                result = await func(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                self._message_queue.task_done()
                await sleep(1)  # 消息发送间隔1秒

    async def _queue_message(self, func, *args, **kwargs):
        """
        将消息添加到队列
        """
        future = Future()
        await self._message_queue.put((func, args, kwargs, future))

        if not self._is_processing:
            asyncio.create_task(self._process_message_queue())

        return await future

    async def revoke_message(self, wxid: str, client_msg_id: int, create_time: int, new_msg_id: int) -> bool:
        """撤回消息。

        Args:
            wxid (str): 接收人wxid
            client_msg_id (int): 发送消息的返回值
            create_time (int): 发送消息的返回值
            new_msg_id (int): 发送消息的返回值

        Returns:
            bool: 成功返回True，失败返回False

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "ClientMsgId": client_msg_id, "CreateTime": create_time,
                          "NewMsgId": new_msg_id}
            response = await session.post(f'http://{self.ip}:{self.port}/RevokeMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                logger.info("消息撤回成功: 对方wxid:{} ClientMsgId:{} CreateTime:{} NewMsgId:{}",
                            wxid,
                            client_msg_id,
                            new_msg_id)
                return True
            else:
                self.error_handler(json_resp)

    async def send_text_message(self, wxid: str, content: str, at: list[str] = None) -> tuple[int, int, int]:
        """发送文本消息。

        Args:
            wxid (str): 接收人wxid
            content (str): 消息内容
            at (list[str], optional): 要@的用户列表. Defaults to None.

        Returns:
            tuple[int, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_text_message, wxid, content, at)

    async def _send_text_message(self, wxid: str, content: str, at: list[str] = None) -> tuple[int, int, int]:
        """
        实际发送文本消息的方法
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        if at is None:
            at = []
        at_str = ",".join(at)
                
        # 处理图片链接
        img_pattern = r'!\[.*?\]\((.*?)\)'
        img_matches = re.findall(img_pattern, content)
        
        # 提取图片链接并移除markdown格式
        content = re.sub(img_pattern, '', content).strip()
        # 如果有图片链接，保存供后续使用
        if img_matches:
            self.last_img_url = img_matches[0]
            await self._send_image_message(wxid, image_base64=self.last_img_url)

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Content": content, "Type": 1, "At": at_str}
            response = await session.post(f'http://{self.ip}:{self.port}/SendTextMsg', json=json_param)
            json_resp = await response.json()
            if json_resp.get("Success"):
                logger.info("发送文字消息: 对方wxid:{} at:{} 内容:{}", wxid, at, content)
                data = json_resp.get("Data")
                return data.get("List")[0].get("ClientMsgid"), data.get("List")[0].get("Createtime"), data.get("List")[
                    0].get("NewMsgId")
            else:
                self.error_handler(json_resp)

    async def send_image_message(self, wxid: str, image_path: str = "", image_base64: str = "") -> tuple[int, int, int]:
        """发送图片消息。

        Args:
            wxid (str): 接收人wxid
            image_path (str, optional): 图片路径，与image_base64二选一. Defaults to "".
            image_base64 (str, optional): 图片base64编码，与image_path二选一. Defaults to "".

        Returns:
            tuple[int, int, int]: 返回(ClientImgId, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            ValueError: image_path和image_base64都为空或都不为空时
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_image_message, wxid, image_path, image_base64)

    async def _send_image_message(self, wxid: str, image_path: str = "", image_base64: str = "") -> tuple[
        int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        if bool(image_path) == bool(image_base64):
            raise ValueError("Please provide either image_path or image_base64")

        if image_path:
            with open(image_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode()
        elif image_base64.startswith(('http://', 'https://')):
            async with aiohttp.ClientSession() as session:
                async with session.get(image_base64) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        image_base64 = base64.b64encode(image_data).decode()
                    else:
                        raise ValueError(f"Failed to download image from {image_base64}")
        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Base64": image_base64}
            response = await session.post(f'http://{self.ip}:{self.port}/SendImageMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                json_param.pop('Base64')
                logger.info("发送图片消息: 对方wxid:{} 图片base64略", wxid)
                data = json_resp.get("Data")
                return data.get("ClientImgId").get("string"), data.get("CreateTime"), data.get("Newmsgid")
            else:
                self.error_handler(json_resp)

    async def send_video_message(self, wxid: str, video_base64: str = "", image_base64: str = "", video_path: str = "",
                                 image_path: str = "") -> tuple[int, int]:
        """发送视频消息。

        Args:
            wxid (str): 接收人wxid
            video_base64 (str, optional): 视频base64编码，与video_path二选一. Defaults to "".
            image_base64 (str, optional): 视频封面图片base64编码，与image_path二选一. Defaults to "".
            video_path (str, optional): 视频文件路径，与video_base64二选一. Defaults to "".
            image_path (str, optional): 视频封面图片路径，与image_base64二选一. Defaults to "".

        Returns:
            tuple[int, int]: 返回(ClientMsgid, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            ValueError: 视频或图片参数都为空或都不为空时
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_video_message, wxid, video_base64, image_base64, video_path,
                                         image_path)

    async def _send_video_message(self, wxid: str, video_base64: str = "", image_base64: str = "", video_path: str = "",
                                  image_path: str = "") -> tuple[int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        if bool(video_path) == bool(video_base64):
            raise ValueError("Please provide either video_path or video_base64")
        if bool(image_path) == bool(image_base64):
            raise ValueError("Please provide either image_path or image_base64")

        # get video base64, and get duration of video, 1000unit = 1 second
        if video_path:
            with open(video_path, "rb") as video_file:
                video_base64 = base64.b64encode(video_file.read()).decode()
            video = mp.VideoFileClip(video_path)
            duration = int(video.duration * 1000)
        elif video_base64:
            video = mp.VideoFileClip(BytesIO(base64.b64decode(video_base64)))
            duration = int(video.duration * 1000)
        else:
            raise ValueError("Please provide either video_path or video_base64")

        # get image base64
        if image_path:
            with open(image_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode()

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Base64": video_base64, "ImageBase64": image_base64,
                          "PlayLength": duration}
            response = await session.post(f'http://{self.ip}:{self.port}/SendVideoMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                json_param.pop('Base64')
                json_param.pop('ImageBase64')
                logger.info("发送视频消息: 对方wxid:{} 时长:{} 视频base64略 图片base64略", wxid, duration)
                data = json_resp.get("Data")
                return int(data.get("clientMsgId")), data.get("newMsgId")
            else:
                self.error_handler(json_resp)

    async def send_voice_message(self, wxid: str, voice_base64: str = "", voice_path: str = "", format: str = "amr") -> \
            tuple[int, int, int]:
        """发送语音消息。

        Args:
            wxid (str): 接收人wxid
            voice_base64 (str, optional): 语音base64编码，与voice_path二选一. Defaults to "".
            voice_path (str, optional): 语音文件路径，与voice_base64二选一. Defaults to "".
            format (str, optional): 语音格式，支持amr/wav/mp3. Defaults to "amr".

        Returns:
            tuple[int, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            ValueError: voice_path和voice_base64都为空或都不为空时，或format不支持时
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_voice_message, wxid, voice_base64, voice_path, format)

    async def _send_voice_message(self, wxid: str, voice_base64: str = "", voice_path: str = "", format: str = "amr") -> \
            tuple[int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")
        elif bool(voice_path) == bool(voice_base64):
            raise ValueError("Please provide either voice_path or voice_base64")
        elif format not in ["amr", "wav", "mp3"]:
            raise ValueError("format must be one of amr, wav, mp3")

        duration = 0
        if format == "amr":
            if voice_path:
                with open(voice_path, 'rb') as f:
                    voice_base64 = base64.b64encode(f.read()).decode()
                audio = AudioSegment.from_file(voice_path, format="amr")
                duration = len(audio)
            elif voice_base64:
                audio = AudioSegment.from_file(BytesIO(base64.b64decode(voice_base64)), format="amr")
                duration = len(audio)
        elif format == "wav":
            if voice_path:
                audio = AudioSegment.from_wav(voice_path).set_channels(1).set_frame_rate(16000)
                duration = len(audio)
                voice_base64 = base64.b64encode(
                    await pysilk.async_encode(audio.raw_data, sample_rate=audio.frame_rate)).decode()
            elif voice_base64:
                audio = AudioSegment.from_wav(BytesIO(base64.b64decode(voice_base64))).set_channels(1).set_frame_rate(
                    16000)
                duration = len(audio)
                voice_base64 = base64.b64encode(
                    await pysilk.async_encode(audio.raw_data, sample_rate=audio.frame_rate)).decode()
        elif format == "mp3":
            if voice_path:
                audio = AudioSegment.from_mp3(voice_path).set_channels(1).set_frame_rate(16000)
                duration = len(audio)
                voice_base64 = base64.b64encode(
                    await pysilk.async_encode(audio.raw_data, sample_rate=audio.frame_rate)).decode()
            elif voice_base64:
                audio = AudioSegment.from_mp3(BytesIO(base64.b64decode(voice_base64))).set_channels(1).set_frame_rate(
                    16000)
                duration = len(audio)
                voice_base64 = base64.b64encode(
                    await pysilk.async_encode(audio.raw_data, sample_rate=audio.frame_rate)).decode()
        else:
            raise ValueError("Please provide either voice_path or voice_base64")

        format_dict = {"amr": 0, "wav": 4, "mp3": 4}

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Base64": voice_base64, "VoiceTime": duration,
                          "Type": format_dict[format]}
            response = await session.post(f'http://{self.ip}:{self.port}/SendVoiceMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                json_param.pop('Base64')
                logger.info("发送语音消息: 对方wxid:{} 时长:{} 格式:{} 音频base64略", wxid, duration, format)
                data = json_resp.get("Data")
                return int(data.get("ClientMsgId")), data.get("CreateTime"), data.get("NewMsgId")
            else:
                self.error_handler(json_resp)

    async def send_link_message(self, wxid: str, url: str, title: str = "", description: str = "",
                                thumb_url: str = "") -> tuple[str, int, int]:
        """发送链接消息。

        Args:
            wxid (str): 接收人wxid
            url (str): 跳转链接
            title (str, optional): 标题. Defaults to "".
            description (str, optional): 描述. Defaults to "".
            thumb_url (str, optional): 缩略图链接. Defaults to "".

        Returns:
            tuple[str, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_link_message, wxid, url, title, description, thumb_url)

    async def _send_link_message(self, wxid: str, url: str, title: str = "", description: str = "",
                                 thumb_url: str = "") -> tuple[int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Url": url, "Title": title, "Desc": description,
                          "ThumbUrl": thumb_url}
            response = await session.post(f'http://{self.ip}:{self.port}/SendShareLink', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                logger.info("发送链接消息: 对方wxid:{} 链接:{} 标题:{} 描述:{} 缩略图链接:{}",
                            wxid,
                            url,
                            title,
                            description,
                            thumb_url)
                data = json_resp.get("Data")
                return data.get("clientMsgId"), data.get("createTime"), data.get("newMsgId")
            else:
                self.error_handler(json_resp)

    async def send_emoji_message(self, wxid: str, md5: str, total_length: int) -> list[dict]:
        """发送表情消息。

        Args:
            wxid (str): 接收人wxid
            md5 (str): 表情md5值
            total_length (int): 表情总长度

        Returns:
            list[dict]: 返回表情项列表(list of emojiItem)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_emoji_message, wxid, md5, total_length)

    async def _send_emoji_message(self, wxid: str, md5: str, total_length: int) -> tuple[int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Md5": md5, "TotalLen": total_length}
            response = await session.post(f'http://{self.ip}:{self.port}/SendEmojiMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                logger.info("发送表情消息: 对方wxid:{} md5:{} 总长度:{}", wxid, md5, total_length)
                return json_resp.get("Data").get("emojiItem")
            else:
                self.error_handler(json_resp)

    async def send_card_message(self, wxid: str, card_wxid: str, card_nickname: str, card_alias: str = "") -> tuple[
        int, int, int]:
        """发送名片消息。

        Args:
            wxid (str): 接收人wxid
            card_wxid (str): 名片用户的wxid
            card_nickname (str): 名片用户的昵称
            card_alias (str, optional): 名片用户的备注. Defaults to "".

        Returns:
            tuple[int, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_card_message, wxid, card_wxid, card_nickname, card_alias)

    async def _send_card_message(self, wxid: str, card_wxid: str, card_nickname: str, card_alias: str = "") -> tuple[
        int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "CardWxid": card_wxid, "CardAlias": card_alias,
                          "CardNickname": card_nickname}
            response = await session.post(f'http://{self.ip}:{self.port}/SendCardMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                logger.info("发送名片消息: 对方wxid:{} 名片wxid:{} 名片备注:{} 名片昵称:{}", wxid,
                            card_wxid,
                            card_alias,
                            card_nickname)
                data = json_resp.get("Data")
                return data.get("List")[0].get("ClientMsgid"), data.get("List")[0].get("Createtime"), data.get("List")[
                    0].get("NewMsgId")
            else:
                self.error_handler(json_resp)

    async def send_app_message(self, wxid: str, xml: str, type: int) -> tuple[str, int, int]:
        """发送应用消息。

        Args:
            wxid (str): 接收人wxid
            xml (str): 应用消息的xml内容
            type (int): 应用消息类型

        Returns:
            tuple[str, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_app_message, wxid, xml, type)

    async def _send_app_message(self, wxid: str, xml: str, type: int) -> tuple[int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Xml": xml, "Type": type}
            response = await session.post(f'http://{self.ip}:{self.port}/SendAppMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                json_param["Xml"] = json_param["Xml"].replace("\n", "")
                logger.info("发送app消息: 对方wxid:{} 类型:{} xml:{}", wxid, type, json_param["Xml"])
                return json_resp.get("Data").get("clientMsgId"), json_resp.get("Data").get(
                    "createTime"), json_resp.get("Data").get("newMsgId")
            else:
                self.error_handler(json_resp)

    async def send_cdn_file_msg(self, wxid: str, xml: str) -> tuple[str, int, int]:
        """转发文件消息。

        Args:
            wxid (str): 接收人wxid
            xml (str): 要转发的文件消息xml内容

        Returns:
            tuple[str, int, int]: 返回(ClientMsgid, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_cdn_file_msg, wxid, xml)

    async def _send_cdn_file_msg(self, wxid: str, xml: str) -> tuple[int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Content": xml}
            response = await session.post(f'http://{self.ip}:{self.port}/SendCDNFileMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                logger.info("转发文件消息: 对方wxid:{} xml:{}", wxid, xml)
                data = json_resp.get("Data")
                return data.get("clientMsgId"), data.get("createTime"), data.get("newMsgId")
            else:
                self.error_handler(json_resp)

    async def send_cdn_img_msg(self, wxid: str, xml: str) -> tuple[str, int, int]:
        """转发图片消息。

        Args:
            wxid (str): 接收人wxid
            xml (str): 要转发的图片消息xml内容

        Returns:
            tuple[str, int, int]: 返回(ClientImgId, CreateTime, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_cdn_img_msg, wxid, xml)

    async def _send_cdn_img_msg(self, wxid: str, xml: str) -> tuple[int, int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Content": xml}
            response = await session.post(f'http://{self.ip}:{self.port}/SendCDNImgMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                logger.info("转发图片消息: 对方wxid:{} xml:{}", wxid, xml)
                data = json_resp.get("Data")
                return data.get("ClientImgId").get("string"), data.get("CreateTime"), data.get("Newmsgid")
            else:
                self.error_handler(json_resp)

    async def send_cdn_video_msg(self, wxid: str, xml: str) -> tuple[str, int]:
        """转发视频消息。

        Args:
            wxid (str): 接收人wxid
            xml (str): 要转发的视频消息xml内容

        Returns:
            tuple[str, int]: 返回(ClientMsgid, NewMsgId)

        Raises:
            UserLoggedOut: 未登录时调用
            BanProtection: 登录新设备后4小时内操作
            根据error_handler处理错误
        """
        return await self._queue_message(self._send_cdn_video_msg, wxid, xml)

    async def _send_cdn_video_msg(self, wxid: str, xml: str) -> tuple[int, int]:
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "ToWxid": wxid, "Content": xml}
            response = await session.post(f'http://{self.ip}:{self.port}/SendCDNVideoMsg', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                logger.info("转发视频消息: 对方wxid:{} xml:{}", wxid, xml)
                data = json_resp.get("Data")
                return data.get("clientMsgId"), data.get("newMsgId")
            else:
                self.error_handler(json_resp)

    async def sync_message(self) -> dict:
        """同步消息。

        Returns:
            dict: 返回同步到的消息数据

        Raises:
            UserLoggedOut: 未登录时调用
            根据error_handler处理错误
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")

        async with aiohttp.ClientSession() as session:
            json_param = {"Wxid": self.wxid, "Scene": 0, "Synckey": ""}
            response = await session.post(f'http://{self.ip}:{self.port}/Sync', json=json_param)
            json_resp = await response.json()

            if json_resp.get("Success"):
                return json_resp.get("Data")
            else:
                self.error_handler(json_resp)
