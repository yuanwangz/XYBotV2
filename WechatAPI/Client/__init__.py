from WechatAPI.errors import *
from .base import WechatAPIClientBase, Proxy, Section
from .chatroom import ChatroomMixin
from .friend import FriendMixin
from .hongbao import HongBaoMixin
from .login import LoginMixin
from .message import MessageMixin
from .protect import protector
from .protect import protector
from .tool import ToolMixin
from .user import UserMixin
import re


class WechatAPIClient(LoginMixin, MessageMixin, FriendMixin, ChatroomMixin, UserMixin,
                      ToolMixin, HongBaoMixin):

    # 这里都是需要结合多个功能的方法

    async def send_at_message(self, wxid: str, content: str, at: list[str]) -> tuple[int, int, int]:
        """发送@消息

        Args:
            wxid (str): 接收人
            content (str): 消息内容
            at (list[str]): 要@的用户ID列表

        Returns:
            tuple[int, int, int]: 包含以下三个值的元组:
                - ClientMsgid (int): 客户端消息ID
                - CreateTime (int): 创建时间
                - NewMsgId (int): 新消息ID

        Raises:
            UserLoggedOut: 用户未登录时抛出
            BanProtection: 新设备登录4小时内操作时抛出
        """
        if not self.wxid:
            raise UserLoggedOut("请先登录")
        elif not self.ignore_protect and protector.check(14400):
            raise BanProtection("登录新设备后4小时内请不要操作以避免风控")
        
        output = ""
        for id in at:
            nickname = await self.get_nickname(id)
            output += f"@{nickname}\u2005"

        # 处理图片链接
        img_pattern = r'!\[.*?\]\((.*?)\)'
        img_matches = re.findall(img_pattern, content)
        
        # 提取图片链接并移除markdown格式
        cleaned_content = re.sub(img_pattern, '', content).strip()
        
        # 拼接处理后的内容
        output += cleaned_content
        
        # 如果有图片链接，保存供后续使用
        if img_matches:
            self.last_img_url = img_matches[0]
        
        self.send_image_message(wxid, image_base64=self.last_img_url)

        return await self.send_text_message(wxid, output, at)
