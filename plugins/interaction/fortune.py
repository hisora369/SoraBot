import random
from datetime import date
from typing import Optional

from ncatbot.plugin_system import NcatBotPlugin, command_registry
from ncatbot.core.event import BaseMessageEvent
from ncatbot.utils import get_log
from plugins.sys.core import dao

LOG = get_log("FortunePlugin")


class FortunePlugin(NcatBotPlugin):
    name = "FortunePlugin"
    version = "1.0.0"
    description = "每日运势查询插件"

    # 运势等级定义
    FORTUNE_LEVELS = {
        "大吉": {"desc": "鸿运当头，万事如意！", "lucky_num": range(1, 10)},
        "中吉": {"desc": "顺遂平安，小有收获。", "lucky_num": range(10, 20)},
        "小吉": {"desc": "平稳发展，积少成多。", "lucky_num": range(20, 30)},
        "平": {"desc": "保持平常心，静待时机。", "lucky_num": range(30, 40)},
        "小凶": {"desc": "谨慎行事，避免冲动。", "lucky_num": range(40, 50)},
        "中凶": {"desc": "诸事不顺，多加小心。", "lucky_num": range(50, 60)},
        "大凶": {"desc": "厄运缠身，宜静不宜动。", "lucky_num": range(60, 70)},
    }

    # 幸运颜色
    LUCKY_COLORS = ["红色", "橙色", "黄色", "绿色", "蓝色", "紫色", "粉色", "白色", "黑色", "金色"]

    # 宜/忌事项模板
    GOOD_THINGS = ["出行", "学习", "工作", "交友", "投资", "休息", "购物", "约会", "运动", "阅读", "出勤", ]
    BAD_THINGS = ["冲动消费", "熬夜", "争吵", "冒险", "拖延", "抱怨", "八卦", "暴饮暴食", "社交", "购物狂", "懒惰", "拖延症"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cache_date = date.today()
        self.fortune_cache = {}  # 内存缓存，避免重复查询数据库

    async def on_load(self):
        """插件加载时初始化"""
        LOG.info(f"插件 {self.name} v{self.version} 加载成功")
        LOG.info("今日运势插件已就绪！")

    @command_registry.command('运势', aliases=['fortune', 'luck', '今日运势', 'jrrs'], description='查询今日运势')
    async def check_fortune(self, event: BaseMessageEvent) -> None:
        """查询用户今日运势"""
        qq = event.user_id
        today = date.today()

        # 检查日期变更，清理缓存
        if today != self.cache_date:
            self.fortune_cache.clear()
            self.cache_date = today
            LOG.info("日期变更，已清理运势缓存")

        # 检查内存缓存
        if qq in self.fortune_cache:
            LOG.debug(f"用户 {qq} 从缓存获取运势")
            await event.reply(self.fortune_cache[qq])
            return

        # 查询数据库
        fortune_data = await self._get_fortune_from_db(qq, today)

        if fortune_data:
            # 存入缓存
            self.fortune_cache[qq] = fortune_data
            await event.reply(fortune_data)
        else:
            # 生成新运势
            new_fortune = self._generate_fortune(qq, today)

            # 保存到数据库（带24小时TTL）
            await self._save_fortune(qq, today, new_fortune)

            # 存入缓存
            self.fortune_cache[qq] = new_fortune

            LOG.info(f"用户 {qq} 生成新运势: {new_fortune.split(chr(10))[0]}")
            await event.reply(new_fortune)

    def _generate_fortune(self, qq: str, today: date) -> str:
        """生成今日运势"""
        # 使用用户ID和日期作为随机种子，确保同一天同一用户运势不变
        seed = int(f"{qq}{today.strftime('%Y%m%d')}")
        random.seed(seed)

        # 随机选择运势等级
        level = random.choice(list(self.FORTUNE_LEVELS.keys()))
        level_info = self.FORTUNE_LEVELS[level]

        # 生成幸运数字
        lucky_num = random.choice(list(level_info["lucky_num"]))

        # 生成幸运颜色
        lucky_color = random.choice(self.LUCKY_COLORS)

        # 生成宜/忌事项
        good_things = random.sample(self.GOOD_THINGS, 3)
        bad_things = random.sample(self.BAD_THINGS, 2)

        # 格式化输出
        fortune_text = (
            f"📅 {today.strftime('%Y年%m月%d日')} 运势\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎯 综合运势：{level}\n"
            f"📊 运势详解：{level_info['desc']}\n"
            f"🔢 幸运数字：{lucky_num}\n"
            f"🌈 幸运颜色：{lucky_color}\n"
            f"✅ 今日宜：{', '.join(good_things)}\n"
            f"❌ 今日忌：{', '.join(bad_things)}\n"
            f"━━━━━━━━━━━━━━\n"
            f"💡 提示：保持积极心态，好运自然来！"
        )

        return fortune_text

    async def _get_fortune_from_db(self, qq: str, today: date) -> Optional[str]:
        """从数据库查询今日运势"""
        key = f"fortune:{today.isoformat()}:{qq}"
        value = await dao.get_key_ttl(key)
        return value

    async def _save_fortune(self, qq: str, today: date, fortune: str) -> None:
        """保存运势到数据库（24小时TTL）"""
        key = f"fortune:{today.isoformat()}:{qq}"
        # 设置24小时过期（86400秒）
        await dao.set_key_ttl(key, fortune, 86400)

    async def on_close(self):
        """插件卸载时清理"""
        LOG.info(f"插件 {self.name} 卸载成功")
        self.fortune_cache.clear()


__all__ = ["FortunePlugin"]