# plugins/sys/ttl_cleaner.py
import asyncio
from asyncio import sleep
from ncatbot.plugin_system import NcatBotPlugin
from ncatbot.utils import get_log          # 引入官方日志
from plugins.sys.core import dao

LOG = get_log("TTLCleaner")                # 显式 logger


class TTLCleanerPlugin(NcatBotPlugin):
    name = "TTLCleaner"
    version = "1.0"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._run = True                     # 在 __init__ 里定义

    async def on_load(self):
        # 用官方提供的调度器（如果版本没有，就用手动 asyncio.create_task）
        self.task = asyncio.create_task(self._loop())
        LOG.info(f"插件 {self.name} 加载成功")

    async def _loop(self):
        while self._run:
            await sleep(3600)
            cleaned = await dao.ttl_cleanup()
            if cleaned:
                LOG.info(f"[TTLCleaner] 清理 {cleaned} 条过期 KV")

    async def on_close(self):
        self._run = False
        self.task.cancel()                   # 优雅停任务
        try:
            await self.task
        except asyncio.CancelledError:
            pass


__all__ = ["TTLCleanerPlugin"]