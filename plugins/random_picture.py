import tomllib
import traceback

import aiohttp
from loguru import logger

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class RandomPicture(PluginBase):
    description = "随机图片"
    author = "HenryXiaoYang"
    version = "1.0.0"

    def __init__(self):
        super().__init__()

        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["RandomPicture"]

        self.enable = config["enable"]
        self.command = config["command"]

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        content = str(message["Content"]).strip()
        command = content.split(" ")

        if not len(command) or command[0] not in self.command:
            return

        api_url = "https://api.52vmy.cn/api/img/tu/man?type=text"

        try:
            conn_ssl = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.request("GET", url=api_url, connector=conn_ssl) as req:
                pic_url = await req.text()

            async with aiohttp.request("GET", url=pic_url, connector=conn_ssl) as req:
                content = await req.read()

            await conn_ssl.close()

            pic = bot.byte_to_base64(content)
            await bot.send_image_message(message["FromWxid"], image_base64=pic)

        except Exception as error:
            out_message = f"-----Bot-----\n出现错误❌！\n{error}"
            logger.error(traceback.format_exc())

            await bot.send_text_message(message["FromWxid"], out_message)
