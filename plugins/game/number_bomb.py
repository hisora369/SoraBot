# plugins/number_bomb.py
from random import randint
from typing import TypedDict
from ncatbot.plugin_system import command_registry, filter_registry
from ncatbot.core.event import BaseMessageEvent, GroupMessageEvent
from plugins.game.game_base import BaseGamePlugin, GameState
from plugins.sys.core import dao
from ncatbot.utils import get_log


LOG = get_log("NumberBomb")

class BombData(TypedDict):
    target: int
    min: int
    max: int

class NumberBombPlugin(BaseGamePlugin[BombData]):
    name = "NumberBomb"
    version = "1.1"
    description = "数字炸弹（持久化+TTL）"

    def init_state(self) -> GameState[BombData]:
        return GameState[BombData](prefix="bomb", ttl=86400)   # 24h 自动过期

    # 可选：启动时打印恢复了多少局
    async def on_load(self) -> None:
        LOG.info(f"插件 {self.name} 加载成功")


    # ---------------- 命令 ----------------
    @command_registry.command("数字炸弹")
    async def start_bomb(self, event: BaseMessageEvent):
        if not isinstance(event, GroupMessageEvent):
            return await event.reply("⚠️ 该游戏只能在群聊中玩哦～")
        gid = event.group_id
        exist = await self.game_load(gid)
        if exist:
            return await event.reply("💣 本局游戏还未结束，直接参与即可！")
        data = BombData(target=randint(1, 100), min=1, max=100)
        await self.game_save(gid, data)
        await event.reply("💣 数字炸弹已启动（1-100）！猜一个数字吧～")

    # ---------------- 群聊监听 ----------------
    @filter_registry.group_filter
    async def guess(self, event: BaseMessageEvent):
        if not isinstance(event, GroupMessageEvent):
            return
        gid = event.group_id
        data = await self.game_load(gid)
        if not data:
            return   # 本群没游戏

        text = event.raw_message.strip()
        if not text.isdigit():
            return
        guess = int(text)
        if guess < data["min"] or guess > data["max"]:
            return await event.reply(f'超出范围！请输入 {data["min"]}-{data["max"]}')

        if guess == data["target"]:
            await dao.add_exp_coin(event.user_id, coin=20)
            await self.game_clear(gid)
            await event.reply("🎉 炸啦！恭喜你获得 20 金币！")
        elif guess < data["target"]:
            data["min"] = guess + 1
            await self.game_save(gid, data)
            await event.reply(f'小了！范围 {data["min"]}-{data["max"]}')
        else:
            data["max"] = guess - 1
            await self.game_save(gid, data)
            await event.reply(f'大了！范围 {data["min"]}-{data["max"]}')

__all__ = ["NumberBombPlugin"]