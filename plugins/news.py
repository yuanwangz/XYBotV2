import asyncio
import tomllib
from random import choice

import aiohttp

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class News(PluginBase):
    description = "新闻插件"
    author = "HenryXiaoYang"
    version = "1.0.0"

    def __init__(self):
        super().__init__()

        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["News"]

        self.enable = config["enable"]
        self.command = config["command"]

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        content = str(message["Content"]).strip()
        command = content.split(" ")

        if command[0] not in self.command:
            return

        if "随机" in command[0]:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://tools.mgtv100.com/external/v1/toutiao/index") as resp:
                    data = await resp.json()

            if data["code"] != 200:
                await bot.send_text_message(message["FromWxid"], "-----Bot-----\n新闻获取失败！")
                return

            result = data.get("data", {}).get("result", {})

            new = choice(result["data"])
            await bot.send_link_message(message["FromWxid"],
                                        title=new["title"],
                                        url=new["url"],
                                        description=f"发布: {new['date']}\n类别: {new['category']}\n作者: {new['author_name']}",
                                        thumb_url=new["thumbnail_pic_s"])

        else:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://zj.v.api.aa1.cn/api/60s-v2/?cc=XYBot") as resp:
                    image_byte = await resp.read()
            await bot.send_image_message(message["FromWxid"], image_base64=bot.byte_to_base64(image_byte))

    @schedule('cron', hour=12)
    async def noon_news(self, bot: WechatAPIClient):
        if not self.enable:
            return

        id_list = []
        wx_seq, chatroom_seq = 0, 0
        while True:
            contact_list = await bot.get_contract_list(wx_seq, chatroom_seq)
            id_list.extend(contact_list["ContactUsernameList"])
            wx_seq = contact_list["CurrentWxcontactSeq"]
            chatroom_seq = contact_list["CurrentChatRoomContactSeq"]
            if contact_list["CountinueFlag"] != 1:
                break

        chatrooms = []
        for id in id_list:
            if id.endswith("@chatroom"):
                chatrooms.append(id)

        async with aiohttp.ClientSession() as session:
            async with session.get("https://zj.v.api.aa1.cn/api/60s-v2/?cc=XYBot") as resp:
                iamge_byte = await resp.read()

        image_base64 = bot.byte_to_base64(iamge_byte)

        for id in chatrooms:
            await bot.send_image_message(id, image_base64=image_base64)
            await asyncio.sleep(2)

    @schedule('cron', hour=18)
    async def night_news(self, bot: WechatAPIClient):
        if not self.enable:
            return

        id_list = []
        wx_seq, chatroom_seq = 0, 0
        while True:
            contact_list = await bot.get_contract_list(wx_seq, chatroom_seq)
            id_list.extend(contact_list["ContactUsernameList"])
            wx_seq = contact_list["CurrentWxcontactSeq"]
            chatroom_seq = contact_list["CurrentChatRoomContactSeq"]
            if contact_list["CountinueFlag"] != 1:
                break

        chatrooms = []
        for id in id_list:
            if id.endswith("@chatroom"):
                chatrooms.append(id)

        async with aiohttp.ClientSession() as session:
            async with session.get("https://v.api.aa1.cn/api/60s-v3/?cc=XYBot") as resp:
                iamge_byte = await resp.read()

        image_base64 = bot.byte_to_base64(iamge_byte)

        for id in chatrooms:
            await bot.send_image_message(id, image_base64=image_base64)
            await asyncio.sleep(2)
