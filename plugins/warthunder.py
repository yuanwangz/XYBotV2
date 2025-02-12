import tomllib

import aiohttp

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class Warthunder(PluginBase):
    description = "战争雷霆玩家查询"
    author = "HenryXiaoYang"
    version = "1.0.0"

    def __init__(self):
        super().__init__()

        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["Warthunder"]

        self.enable = config["enable"]
        self.command = config["command"]
        self.command_format = config["command-format"]

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return

        content = str(message["Content"]).strip()
        command = content.split(" ")

        if command[0] not in self.command:
            return

        if len(command) != 2:
            await bot.send_text_message(message["FromWxid"], self.command_format)
            return

        player_name = content[len(command[0]) + 1:]

        output = (f"\n-----Bot-----\n"
                  f"正在查询玩家 {player_name} 的数据，请稍等...😄")
        a, b, c = await bot.send_at_message(message["FromWxid"], output, [message["SenderWxid"]])

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://wtapi.yangres.com/card/{player_name}") as resp:
                image_byte = await resp.read()

        await bot.send_image_message(message["FromWxid"], image_base64=bot.byte_to_base64(image_byte))

        await bot.revoke_message(message["FromWxid"], a, b, c)
