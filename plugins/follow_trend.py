from loguru import logger
import random
from collections import defaultdict, deque

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message
from utils.plugin_base import PluginBase


class FollowTrendPlugin(PluginBase):
    description = "跟风插件 - 检测群内重复发言并有概率跟风"
    author = "Assistant"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        # 使用defaultdict和deque来记录每个群的最近消息
        # 格式: {room_id: deque([message_content, message_content, ...])}
        self.recent_messages = defaultdict(lambda: deque(maxlen=3))

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        # 只处理群消息
        if not message["IsGroup"]:
            return

        room_id = message["FromWxid"]
        content = message["Content"]
        
        # 记录消息
        self.recent_messages[room_id].append(content)
        # 检查是否有连续三条相同消息
        if (len(self.recent_messages[room_id]) == 3 and 
            len(set(self.recent_messages[room_id])) == 1):
            # 50%概率跟风
            if random.random() < 0.5:
                await bot.send_text_message(room_id, content)
                logger.info(f"跟风发送消息: {content} 到群: {room_id}") 