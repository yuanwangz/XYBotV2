import hashlib
from loguru import logger
import random
import tomllib

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message
from utils.plugin_base import PluginBase


class KPIPlugin(PluginBase):
    description = "绩效考核插件"
    author = "Assistant"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["KPI"]

        self.enable = config["enable"]
        self.command = config["command"]
        self.kpi_url = config["kpi-url"]

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
        
        wxid_md5 = hashlib.md5(sender_wxid.encode()).hexdigest()
        msg = '您的月度绩效考核填写地址是：'+self.kpi_url+wxid_md5;
        await bot.send_text_message(from_wxid, msg, [sender_wxid] if is_group else [])
        logger.info(f"发送绩效考核链接: {msg} 到: {from_wxid}") 