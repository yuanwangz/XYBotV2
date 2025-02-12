import tomllib
import xml.etree.ElementTree as ET
from typing import Dict, Any

from loguru import logger

from WechatAPI import WechatAPIClient
from WechatAPI.Client import protector
from utils.event_manager import EventManager


class XYBot:
    def __init__(self, bot_client: WechatAPIClient):
        self.bot = bot_client
        self.wxid = None
        self.nickname = None
        self.alias = None
        self.phone = None

        with open("main_config.toml", "rb") as f:
            main_config = tomllib.load(f)

        self.ignore_mode = main_config.get("XYBot", {}).get("ignore-mode", "")
        self.whitelist = main_config.get("XYBot", {}).get("whitelist", [])
        self.blacklist = main_config.get("XYBot", {}).get("blacklist", [])
        self.ignore_protect = main_config.get("XYBot", {}).get("ignore-protection", False)
    def update_profile(self, wxid: str, nickname: str, alias: str, phone: str):
        """更新机器人信息"""
        self.wxid = wxid
        self.nickname = nickname
        self.alias = alias
        self.phone = phone

    async def process_message(self, message: Dict[str, Any]):
        """处理接收到的消息"""
        if not self.ignore_protect and protector.check(14400):
            logger.warning("登录新设备后4小时内请不要操作以避免风控")
            return

        msg_type = message.get("MsgType")

        # 预处理消息
        message["FromWxid"] = message.get("FromUserName").get("string")
        message.pop("FromUserName")
        message["ToWxid"] = message.get("ToWxid").get("string")

        # 处理一下自己发的消息
        if message["FromWxid"] == self.wxid and message["ToWxid"].endswith("@chatroom"):  # 自己发发到群聊
            # 由于是自己发送的消息，所以对于自己来说，From和To是反的
            message["FromWxid"], message["ToWxid"] = message["ToWxid"], message["FromWxid"]


        # 根据消息类型触发不同的事件
        if msg_type == 1:  # 文本消息
            await self.process_text_message(message)

        elif msg_type == 3:  # 图片消息
            await self.process_image_message(message)

        elif msg_type == 34:  # 语音消息
            await self.process_voice_message(message)

        elif msg_type == 43:  # 视频消息
            await self.process_video_message(message)

        elif msg_type == 49:  # xml消息
            await self.process_xml_message(message)

        elif msg_type == 10002:  # 系统消息
            await self.process_system_message(message)

        elif msg_type == 37:  # 好友请求
            await EventManager.emit("friend_request", self.bot, message)

        elif msg_type == 51:
            pass

        else:
            logger.info("未知的消息类型: {}", message)

        # 可以继续添加更多消息类型的处理

    async def process_text_message(self, message: Dict[str, Any]):
        """处理文本消息"""
        # 预处理消息
        message["Content"] = message.get("Content").get("string")

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":\n", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]
            else:  # 绝对是自己发的消息! qwq
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid

        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:  # 自己发的消息
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        try:
            root = ET.fromstring(message["MsgSource"])
            ats = root.find("atuserlist").text if root.find("atuserlist") is not None else ""
        except Exception as e:
            logger.error("解析文本消息失败: {}", e)
            return

        ats = ats.strip(",").split(",")
        message["Ats"] = ats if ats[0] != "" else []

        if self.wxid in ats:
            logger.info("收到被@消息: {}", message)
            if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
                await EventManager.emit("at_message", self.bot, message)
            return

        logger.info("收到文本消息: {}", message)

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            await EventManager.emit("text_message", self.bot, message)

    async def process_image_message(self, message: Dict[str, Any]):
        """处理图片消息"""
        # 预处理消息
        message["Content"] = message.get("Content").get("string").replace("\n", "").replace("\t", "")

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]
            else:  # 绝对是自己发的消息! qwq
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:  # 自己发的消息
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        logger.info("收到图片消息: {}", message)

        # 解析图片消息
        aeskey, cdnmidimgurl = None, None
        try:
            root = ET.fromstring(message["Content"])
            img_element = root.find('img')
            if img_element is not None:
                aeskey = img_element.get('aeskey')
                cdnmidimgurl = img_element.get('cdnmidimgurl')
        except Exception as e:
            logger.error("解析图片消息失败: {}", e)
            return

        # 下载图片
        if aeskey and cdnmidimgurl:
            message["Content"] = await self.bot.download_image(aeskey, cdnmidimgurl)

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            await EventManager.emit("image_message", self.bot, message)

    async def process_voice_message(self, message: Dict[str, Any]):
        """处理语音消息"""
        # 预处理消息
        message["Content"] = message.get("Content").get("string").replace("\n", "").replace("\t", "")

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]
            else:  # 绝对是自己发的消息! qwq
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:  # 自己发的消息
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        logger.info("收到语音消息: {}", message)

        if message["IsGroup"]:
            # 解析语音消息
            voiceurl, length = None, None
            try:
                root = ET.fromstring(message["Content"])
                voicemsg_element = root.find('voicemsg')
                if voicemsg_element is not None:
                    voiceurl = voicemsg_element.get('voiceurl')
                    length = int(voicemsg_element.get('length'))
            except Exception as e:
                logger.error("解析语音消息失败: {}", e)
                return

            # 下载语音
            if voiceurl and length:
                silk_base64 = await self.bot.download_voice(message["MsgId"], voiceurl, length)
                message["Content"] = await self.bot.silk_base64_to_wav_byte(silk_base64)
        else:
            silk_base64 = message["ImgBuf"]["buffer"]
            message["Content"] = await self.bot.silk_base64_to_wav_byte(silk_base64)

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            await EventManager.emit("voice_message", self.bot, message)

    async def process_xml_message(self, message: Dict[str, Any]):
        """处理xml消息"""
        message["Content"] = message.get("Content").get("string").replace("\n", "").replace("\t", "")

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]
            else:  # 绝对是自己发的消息! qwq
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:  # 自己发的消息
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        try:
            root = ET.fromstring(message["Content"])
            type = int(root.find("appmsg").find("type").text)
        except Exception as e:
            logger.error(f"解析xml消息失败: {e}")
            return

        if type == 57:
            await self.process_quote_message(message)
        elif type == 6:
            await self.process_file_message(message)
        elif type == 74:  # 文件消息，但还在上传，不用管
            pass

        else:
            logger.info("未知的xml消息类型: {}", message)

    async def process_quote_message(self, message: Dict[str, Any]):
        """处理引用消息"""
        quote_messsage = {}
        try:
            root = ET.fromstring(message["Content"])
            appmsg = root.find("appmsg")
            text = appmsg.find("title").text
            refermsg = appmsg.find("refermsg")

            quote_messsage["MsgType"] = int(refermsg.find("type").text)

            if quote_messsage["MsgType"] == 1:  # 文本消息
                quote_messsage["NewMsgId"] = refermsg.find("svrid").text
                quote_messsage["ToWxid"] = refermsg.find("fromusr").text
                quote_messsage["FromWxid"] = refermsg.find("chatusr").text
                quote_messsage["Nickname"] = refermsg.find("displayname").text
                quote_messsage["MsgSource"] = refermsg.find("msgsource").text
                quote_messsage["Content"] = refermsg.find("content").text
                quote_messsage["Createtime"] = refermsg.find("createtime").text

            elif quote_messsage["MsgType"] == 49:  # 引用消息
                quote_messsage["NewMsgId"] = refermsg.find("svrid").text
                quote_messsage["ToWxid"] = refermsg.find("fromusr").text
                quote_messsage["FromWxid"] = refermsg.find("chatusr").text
                quote_messsage["Nickname"] = refermsg.find("displayname").text
                quote_messsage["MsgSource"] = refermsg.find("msgsource").text
                quote_messsage["Createtime"] = refermsg.find("createtime").text

                quote_messsage["Content"] = refermsg.find("content").text

                quote_root = ET.fromstring(quote_messsage["Content"])
                quote_appmsg = quote_root.find("appmsg")

                quote_messsage["Content"] = quote_appmsg.find("title").text if isinstance(quote_appmsg.find("title"),
                                                                                          ET.Element) else ""
                quote_messsage["destination"] = quote_appmsg.find("des").text if isinstance(quote_appmsg.find("des"),
                                                                                            ET.Element) else ""
                quote_messsage["action"] = quote_appmsg.find("action").text if isinstance(quote_appmsg.find("action"),
                                                                                          ET.Element) else ""
                quote_messsage["XmlType"] = int(quote_appmsg.find("type").text) if isinstance(quote_appmsg.find("type"),
                                                                                              ET.Element) else 0
                quote_messsage["showtype"] = int(quote_appmsg.find("showtype").text) if isinstance(
                    quote_appmsg.find("showtype"), ET.Element) else 0
                quote_messsage["soundtype"] = int(quote_appmsg.find("soundtype").text) if isinstance(
                    quote_appmsg.find("soundtype"), ET.Element) else 0
                quote_messsage["url"] = quote_appmsg.find("url").text if isinstance(quote_appmsg.find("url"),
                                                                                    ET.Element) else ""
                quote_messsage["lowurl"] = quote_appmsg.find("lowurl").text if isinstance(quote_appmsg.find("lowurl"),
                                                                                          ET.Element) else ""
                quote_messsage["dataurl"] = quote_appmsg.find("dataurl").text if isinstance(
                    quote_appmsg.find("dataurl"), ET.Element) else ""
                quote_messsage["lowdataurl"] = quote_appmsg.find("lowdataurl").text if isinstance(
                    quote_appmsg.find("lowdataurl"), ET.Element) else ""
                quote_messsage["songlyric"] = quote_appmsg.find("songlyric").text if isinstance(
                    quote_appmsg.find("songlyric"), ET.Element) else ""
                quote_messsage["appattach"] = {}
                quote_messsage["appattach"]["totallen"] = int(
                    quote_appmsg.find("appattach").find("totallen").text) if isinstance(
                    quote_appmsg.find("appattach").find("totallen"), ET.Element) else 0
                quote_messsage["appattach"]["attachid"] = quote_appmsg.find("appattach").find(
                    "attachid").text if isinstance(quote_appmsg.find("appattach").find("attachid"), ET.Element) else ""
                quote_messsage["appattach"]["emoticonmd5"] = quote_appmsg.find("appattach").find(
                    "emoticonmd5").text if isinstance(quote_appmsg.find("appattach").find("emoticonmd5"),
                                                      ET.Element) else ""
                quote_messsage["appattach"]["fileext"] = quote_appmsg.find("appattach").find(
                    "fileext").text if isinstance(quote_appmsg.find("appattach").find("fileext"), ET.Element) else ""
                quote_messsage["appattach"]["cdnthumbaeskey"] = quote_appmsg.find("appattach").find(
                    "cdnthumbaeskey").text if isinstance(quote_appmsg.find("appattach").find("cdnthumbaeskey"),
                                                         ET.Element) else ""
                quote_messsage["appattach"]["aeskey"] = quote_appmsg.find("appattach").find(
                    "aeskey").text if isinstance(quote_appmsg.find("appattach").find("aeskey"), ET.Element) else ""
                quote_messsage["extinfo"] = quote_appmsg.find("extinfo").text if isinstance(
                    quote_appmsg.find("extinfo"), ET.Element) else ""
                quote_messsage["sourceusername"] = quote_appmsg.find("sourceusername").text if isinstance(
                    quote_appmsg.find("sourceusername"), ET.Element) else ""
                quote_messsage["sourcedisplayname"] = quote_appmsg.find("sourcedisplayname").text if isinstance(
                    quote_appmsg.find("sourcedisplayname"), ET.Element) else ""
                quote_messsage["thumburl"] = quote_appmsg.find("thumburl").text if isinstance(
                    quote_appmsg.find("thumburl"), ET.Element) else ""
                quote_messsage["md5"] = quote_appmsg.find("md5").text if isinstance(quote_appmsg.find("md5"),
                                                                                    ET.Element) else ""
                quote_messsage["statextstr"] = quote_appmsg.find("statextstr").text if isinstance(
                    quote_appmsg.find("statextstr"), ET.Element) else ""
                quote_messsage["directshare"] = int(quote_appmsg.find("directshare").text) if isinstance(
                    quote_appmsg.find("directshare"), ET.Element) else 0

        except Exception as e:
            logger.error(f"解析引用消息失败: {e}")
            return

        message["Content"] = text
        message["Quote"] = quote_messsage

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            await EventManager.emit("quote_message", self.bot, message)

    async def process_video_message(self, message):
        # 预处理消息
        message["Content"] = message.get("Content").get("string")

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]
            else:  # 绝对是自己发的消息! qwq
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:  # 自己发的消息
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        logger.info("收到视频消息: {}", message)

        message["Video"] = await self.bot.download_video(message["MsgId"])

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            await EventManager.emit("video_message", self.bot, message)

    async def process_file_message(self, message: Dict[str, Any]):
        """处理文件消息"""
        try:
            root = ET.fromstring(message["Content"])
            filename = root.find("appmsg").find("title").text
            attach_id = root.find("appmsg").find("appattach").find("attachid").text
            file_extend = root.find("appmsg").find("appattach").find("fileext").text
        except Exception as error:
            logger.error(f"解析文件消息失败: {error}")
            return

        message["Filename"] = filename
        message["FileExtend"] = file_extend

        logger.info("收到文件消息: {}", message)

        message["File"] = await self.bot.download_attach(attach_id)

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            await EventManager.emit("file_message", self.bot, message)

    async def process_system_message(self, message: Dict[str, Any]):
        """处理系统消息"""
        # 预处理消息
        message["Content"] = message.get("Content").get("string")

        if message["FromWxid"].endswith("@chatroom"):  # 群聊消息
            message["IsGroup"] = True
            split_content = message["Content"].split(":", 1)
            if len(split_content) > 1:
                message["Content"] = split_content[1]
                message["SenderWxid"] = split_content[0]
            else:  # 绝对是自己发的消息! qwq
                message["Content"] = split_content[0]
                message["SenderWxid"] = self.wxid
        else:
            message["SenderWxid"] = message["FromWxid"]
            if message["FromWxid"] == self.wxid:  # 自己发的消息
                message["FromWxid"] = message["ToWxid"]
            message["IsGroup"] = False

        try:
            root = ET.fromstring(message["Content"])
            msg_type = root.attrib["type"]
        except Exception as e:
            logger.error(f"解析系统消息失败: {e}")
            return

        if msg_type == "pat":
            await self.process_pat_message(message)
        elif msg_type == "ClientCheckGetExtInfo":
            pass
        else:
            logger.info("未知的系统消息类型: {}", message)

    async def process_pat_message(self, message: Dict[str, Any]):
        """处理拍一拍请求消息"""
        try:
            root = ET.fromstring(message["Content"])
            pat = root.find("pat")
            patter = pat.find("fromusername").text
            patted = pat.find("pattedusername").text
            pat_suffix = pat.find("patsuffix").text
        except Exception as e:
            logger.error(f"解析pat消息失败: {e}")
            return

        message["Patter"] = patter
        message["Patted"] = patted
        message["PatSuffix"] = pat_suffix

        logger.info("收到拍一拍消息: {}", message)

        if self.ignore_check(message["FromWxid"], message["SenderWxid"]):
            await EventManager.emit("pat_message", self.bot, message)

    def ignore_check(self, FromWxid: str, SenderWxid: str):
        if self.ignore_mode == "Whitelist":
            return (FromWxid in self.whitelist) or (SenderWxid in self.whitelist)
        elif self.ignore_mode == "blacklist":
            return (FromWxid not in self.blacklist) and (SenderWxid not in self.blacklist)
        else:
            return True
