import aiohttp
from loguru import logger
import tomllib

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message
from utils.plugin_base import PluginBase


class HYXJPlugin(PluginBase):
    description = "汉语新解插件"
    author = "Assistant"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["HYXJ"]

        self.enable = config["enable"]
        self.command = config["command"]
        self.api_key = config["api-key"]
    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        is_group = message["IsGroup"]
        from_wxid = message["FromWxid"]
        content = message["Content"]
        sender_wxid = message["SenderWxid"]
        
        content = str(message["Content"]).strip()
        command = content.split(" ")

        if not len(command) or command[0] not in self.command:
            return
        if len(command) < 2 or not command[1]:
            return
        async with aiohttp.ClientSession() as session:
            json_param = {"text": command[1], "apiKey": self.api_key}
            response = await session.post(f'https://hyxj-worker.yuanwan2021.workers.dev/hanyuxinjie', json=json_param)
            json_resp = await response.json()
            if json_resp.get("image"):
                await bot.send_image_message(from_wxid, image_base64=json_resp.get("image"))
            else:
                logger.error(f"汉语新解插件: {json_resp}")
