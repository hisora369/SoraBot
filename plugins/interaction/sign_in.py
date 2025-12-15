from datetime import date
from ncatbot.plugin_system import NcatBotPlugin, command_registry
from ncatbot.core.event import BaseMessageEvent
from plugins.sys.core import dao
import random
from ncatbot.utils import get_log

LOG = get_log("SignIn")

class SignInPlugin(NcatBotPlugin):
    name = 'SignIn'
    version = '1.0'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 内存里记一下今天谁签过到（重启即清空，够用）
        # 记录当前日期和今天签到的用户
        self.cache_date = date.today()
        self.today_cache = set()

    async def on_load(self) -> None:
        LOG.info(f"插件 {self.name} 加载成功")

    @command_registry.command('签到', aliases=['sign'])
    async def sign_in(self, event: BaseMessageEvent) -> None:
        qq = event.user_id
        today = date.today()

        # 检查日期是否变化，如果变了就清空缓存
        if today != self.cache_date:
            self.today_cache.clear()
            self.cache_date = today

        if qq in self.today_cache:
            await event.reply('今天已经签到过啦，明天再来～')
            return

        # 发奖
        extra_reward_exp = random.randint(10, 20)
        extra_reward_coin = random.randint(5, 10)
        await dao.add_exp_coin(qq, exp=100+extra_reward_exp, coin=20+extra_reward_coin)
        self.today_cache.add(qq)

        await event.reply(f'签到成功！经验+100 金币+20 ✨\n额外奖励：经验+{extra_reward_exp} 金币+{extra_reward_coin} ✨')

__all__ = ['SignInPlugin']