from loguru import logger
import tomllib
import aiohttp

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message
from utils.plugin_base import PluginBase


class GroupContactPlugin(PluginBase):
    description = "获取群聊成员插件"
    author = "Assistant"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["GroupContact"]

        self.enable = config["enable"]

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return False

        if not message["Content"].startswith("/获取群成员"):
            return False

        content = str(message["Content"]).replace(" ", "")
        content = content.replace("/获取群成员", "")
        if not content:
            await bot.send_text_message(message["FromWxid"], "获取群成员失败,群Id不存在")
            return True
        member_list = await bot.get_chatroom_member_list(content)
        if not member_list:
            await bot.send_text_message(message["FromWxid"], "获取群成员失败,群不存在")
            return True
        payload = {"content": member_list}

        conn_ssl = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.request("POST", url="https://easychuan.cn/texts", connector=conn_ssl, json=payload) as req:
            resp = await req.json()
        await conn_ssl.close()

        await bot.send_link_message(message["FromWxid"],
                                    url=f"https://easychuan.cn/r/{resp['fetch_code']}?t=t",
                                    title="群成员列表",
                                    description=f"过期时间：{resp['date_expire']}、点击查看群成员列表", )
