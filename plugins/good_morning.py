import asyncio
import tomllib
from datetime import datetime
from random import randint

import aiohttp

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class GoodMorning(PluginBase):
    description = "早上好插件"
    author = "HenryXiaoYang"
    version = "1.0.0"

    def __init__(self):
        super().__init__()

        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["GoodMorning"]

        self.enable = config["enable"]
        self.task_whitelist = config["task-whitelist"]

    @schedule('cron', hour=8, minute=30)
    async def daily_task(self, bot: WechatAPIClient):
        if not self.enable:
            return

        if self.task_whitelist and bot.wx_id not in self.task_whitelist:
            return

        id_list = self.task_whitelist

        # id_list = []
        # wx_seq, chatroom_seq = 0, 0
        # while True:
        #     contact_list = await bot.get_contract_list(wx_seq, chatroom_seq)
        #     id_list.extend(contact_list["ContactUsernameList"])
        #     wx_seq = contact_list["CurrentWxcontactSeq"]
        #     chatroom_seq = contact_list["CurrentChatRoomContactSeq"]
        #     if contact_list["CountinueFlag"] != 1:
        #         break

        chatrooms = []
        for id in id_list:
            if id.endswith("@chatroom"):
                chatrooms.append(id)

        async with aiohttp.request("GET", "https://zj.v.api.aa1.cn/api/bk/?num=1&type=json") as req:
            resp = await req.json()
            history_today = "N/A"
            if resp.get("content"):
                history_today = str(resp.get("content")[0])

        weekend = ["一", "二", "三", "四", "五", "六", "日"]
        message = ("----- Bot -----\n"
                   f"[Sun]早上好！今天是 {datetime.now().strftime('%Y年%m月%d号')}，星期{weekend[datetime.now().weekday()]}。\n"
                   "\n"
                   "📖历史上的今天：\n"
                   f"{history_today}")

        for chatroom in chatrooms:
            await bot.send_text_message(chatroom, message)
            await asyncio.sleep(randint(1, 5))
