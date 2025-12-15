# plugins/sys/game_base.py
import json
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional
from ncatbot.plugin_system import NcatBotPlugin
from plugins.sys.core import dao
from ncatbot.utils import get_log

T = TypeVar("T")   # 游戏状态的数据模型

LOG = get_log("GameBase")


class GameState(ABC, Generic[T]):
    """插件内用，仅封装 KV 读写"""
    def __init__(self, prefix: str, ttl: int = 86400):
        self.prefix = prefix        # 例如 "bomb"
        self.ttl   = ttl            # 默认 24h

    def _key(self, gid: str) -> str:
        return f"{self.prefix}:{gid}"

    async def load(self, gid: str) -> Optional[T]:
        return await dao.get_key_ttl(self._key(gid))

    async def save(self, gid: str, data: T) -> None:
        await dao.set_key_ttl(self._key(gid), data, self.ttl)

    async def clear(self, gid: str) -> None:
        await dao.del_key(self._key(gid))


class BaseGamePlugin(NcatBotPlugin, Generic[T]):
    """
    所有游戏的统一模板：
    1. 分群隔离
    2. 自动持久化 + TTL
    3. 提供 load/save/clear 工具
    """
    def __init__(self, **kwargs):
        # 先让父类把注入的参数全吃掉
        super().__init__(**kwargs)
        # 再初始化我们自己的属性
        self.state: GameState[T] = self.init_state()

    async def on_load(self) -> None:
        LOG.info(f"插件 {self.name} 加载成功")

    @abstractmethod
    def init_state(self) -> GameState[T]:
        """子类返回一个 GameState 实例，指定前缀与 TTL"""
        raise NotImplementedError

    # 快捷方法
    async def game_load(self, gid: str) -> Optional[T]:
        return await self.state.load(gid)

    async def game_save(self, gid: str, data: T) -> None:
        await self.state.save(gid, data)

    async def game_clear(self, gid: str) -> None:
        await self.state.clear(gid)