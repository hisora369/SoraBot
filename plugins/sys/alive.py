"""
最轻量“活着”插件
- /hello  命令
- 群消息日志
"""
from ncatbot.plugin_system import NcatBotPlugin, command_registry, filter_registry
from ncatbot.core.event import BaseMessageEvent, GroupMessageEvent   # 记得导入子类
from ncatbot.utils import get_log

LOG = get_log('AlivePlugin')


class AlivePlugin(NcatBotPlugin):
    name = 'Alive'
    version = '1.0'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def on_load(self):
        LOG.info('Alive 插件已加载')

    # ------ 命令 ------
    @command_registry.command('hello', aliases=['hi'])
    async def hello(self, event: BaseMessageEvent):
        await event.reply('你好，SoraBot 已上线 🎉')

    # ------ 日志 ------
    @filter_registry.group_filter                    # 只让群聊事件进来
    async def log_group_msg(self, event: BaseMessageEvent):
        # 100% 是群聊，但保险起见再判断一次
        if isinstance(event, GroupMessageEvent):
            LOG.info(f"群[{event.group_id}] 用户[{event.user_id}] 说：{event.raw_message}")
        else:
            # 永远不会进这里，因为 group_filter 已过滤
            pass


__all__ = ['AlivePlugin']