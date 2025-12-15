from ncatbot.plugin_system import NcatBotPlugin, command_registry
from ncatbot.core.event import BaseMessageEvent
from .core import dao
from ncatbot.utils import get_log

LOG = get_log("Wallet")

class WalletPlugin(NcatBotPlugin):
    name = 'Wallet'
    version = '1.0'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def on_load(self):
        LOG.info(f"插件 {self.name} 加载成功")

    @command_registry.command('账户')
    async def wallet(self, event: BaseMessageEvent):
        user = await dao.get_user(event.user_id)
        if not user:
            await event.reply('还没签到过，暂无余额～')
            return
        await event.reply(f'你有 金币 {user.coin}  经验 {user.exp} 💰')

__all__ = ['WalletPlugin']