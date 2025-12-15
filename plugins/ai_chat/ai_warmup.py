import asyncio
import time
import random
import aiosqlite  # ✅ 修复1: 添加导入
from typing import Dict, List, Optional

from ncatbot.plugin_system import NcatBotPlugin, command_registry
from ncatbot.core.event import GroupMessageEvent, BaseMessageEvent
from ncatbot.utils import get_log
from plugins.sys.core import dao, DB_PATH  # ✅ 修复2: 导入DB_PATH（模块级变量）

LOG = get_log("WarmGroupPlugin")


class WarmGroupPlugin(NcatBotPlugin):
    """AI暖群插件 - 自动检测沉默群聊并发送暖场消息"""

    name = "WarmGroupPlugin"
    version = "1.0.2"  # 修复版本号
    description = "AI暖群助手，自动检测群聊活跃度并发送暖场话题"
    dependencies = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ai_core = None
        self.group_last_active: Dict[str, float] = {}
        self._session_lock = asyncio.Lock()

    async def on_load(self):
        """插件加载时初始化"""
        LOG.info(f"加载 {self.name} v{self.version}")

        # 注册配置项
        self._register_configs()

        # 初始化 AI 核心
        await self._init_ai_core()

        # ✅ 修复6: 从数据库恢复群聊活跃状态
        await self._restore_group_activity()

        # 注册命令
        self._register_commands()

        # 监听群消息
        self.hid_group_msg = self.register_handler(
            "ncatbot.group_message_event",
            self.on_group_message
        )

        # 启动定时检查任务
        self.task = asyncio.create_task(self._warm_group_loop())

        LOG.info(f"{self.name} 加载成功")

    async def _restore_group_activity(self):
        """✅ 修复6: 从数据库恢复群聊活跃状态"""
        try:
            # ✅ 修复2: 使用 DB_PATH（模块级变量）
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute(
                    'SELECT DISTINCT group_id, MAX(timestamp) '
                    'FROM group_messages '
                    'WHERE timestamp > ? '
                    'GROUP BY group_id',
                    (time.time() - 7 * 24 * 3600,)  # 最近7天
                )
                rows = await cursor.fetchall()

                for row in rows:
                    group_id = row[0]
                    last_time = float(row[1])
                    self.group_last_active[group_id] = last_time
                    LOG.info(f"恢复群 {group_id} 活跃记录")

                LOG.info(f"共恢复 {len(rows)} 个群的活跃记录")
        except Exception as e:
            LOG.warning(f"恢复群聊状态失败: {e}，将开始新的追踪")

    def _register_configs(self):
        """注册插件配置项"""
        # 基础配置
        self.register_config("enabled", "true")
        self.register_config("check_interval", "300")
        self.register_config("inactive_hours", "4.0")
        self.register_config("min_messages_threshold", "5")
        self.register_config("trigger_probability", "1.0")
        self.register_config("cooldown_hours", "2.0")

        # AI 配置
        self.register_config("ai_api_key", "Bearer gwoOvnMxlStOJZQIQApq:PVFOxjBhXaNArYLcnnzS")
        self.register_config("ai_api_url", "https://spark-api-open.xf-yun.com/v1/chat/completions")
        self.register_config("ai_model", "Lite")
        self.register_config("ai_temperature", "1.5")
        self.register_config("ai_max_tokens", "150")

        # 暖群提示词
        self.register_config("warm_prompts", """你是一个暖场小助手，请生成一个有趣的话题来活跃群聊。要求：
1. 话题要有趣、轻松，能引发讨论
2. 可以是开放性问题、趣味调查、热点话题等
3. 语气亲切自然，像朋友聊天
4. 长度在30-50字之间
5. 不要表情包，纯文字

示例话题：
- "周末大家都打算怎么过呀？"
- "最近有什么好听的歌推荐吗？"
- "如果中了100万，你会怎么花？"
- "分享一下你最近遇到的最有趣的事吧！""")

    async def _init_ai_core(self):
        """初始化 AI 核心"""
        from plugins.ai_chat.aichat_core import AIChatCore

        self.ai_core = AIChatCore({
            "api_key": self.config.get("ai_api_key", ""),
            "api_url": self.config.get("ai_api_url", ""),
            "model": self.config.get("ai_model", "Lite"),
            "temperature": float(self.config.get("ai_temperature", 1.5)),
            "max_tokens": int(self.config.get("ai_max_tokens", 150)),
            "max_input_length": 100,
            "max_response_length": 150,
            "system_prompt": self.config.get("warm_prompts", "")
        })

    def _register_commands(self):
        """注册命令"""
        plugin = self

        @command_registry.command("warmgroup", aliases=["暖群"], description="手动触发暖群消息")
        async def warmgroup_cmd(event: BaseMessageEvent):
            """手动触发暖群"""
            if isinstance(event, GroupMessageEvent):
                # await event.reply("🤖 正在生成暖群消息，请稍候...")
                await plugin._trigger_warm_message(str(event.group_id))
                # ✅ 修复3: 手动触发也更新冷却时间
                await plugin._set_last_trigger(str(event.group_id), time.time())
            else:
                await event.reply("⚠️ 此命令仅在群聊中可用")

        @command_registry.command("warm_config", description="查看暖群配置")
        async def warm_config_cmd(event: BaseMessageEvent):
            """查看配置"""
            config_info = f"""🤖 暖群配置信息：
📊 检测间隔: {int(self.config.get('check_interval', 300)) // 60} 分钟
⏰ 无消息阈值: {self.config.get('inactive_hours', 4)} 小时
🎯 触发概率: {float(self.config.get('trigger_probability', 1.0)) * 100}%
❄️ 触发后冷却: {self.config.get('cooldown_hours', 2)} 小时
💬 最少消息数: {self.config.get('min_messages_threshold', 5)} 条
🚀 当前状态: {'已启用' if self._bool_config('enabled') else '已禁用'}"""
            await event.reply(config_info)

    def _bool_config(self, key: str, default: bool = False) -> bool:
        val = self.config.get(key, str(default).lower())
        if isinstance(val, str):
            return val.lower() == "true"
        return bool(val)

    def _int_config(self, key: str, default: int = 0) -> int:
        try:
            return int(self.config.get(key, default))
        except (ValueError, TypeError):
            return default

    def _float_config(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.config.get(key, default))
        except (ValueError, TypeError):
            return default

    async def on_group_message(self, event):
        """监听群消息，更新最后活跃时间"""
        msg: GroupMessageEvent = event.data

        self.group_last_active[str(msg.group_id)] = time.time()

        await dao.store_group_message(
            group_id=str(msg.group_id),
            user_id=str(msg.user_id),
            nickname=msg.sender.nickname,
            message=msg.raw_message[:100]
        )

    async def _warm_group_loop(self):
        """定时检查循环"""
        while True:
            try:
                check_interval = self._int_config("check_interval", 300)
                await asyncio.sleep(check_interval)

                if not self._bool_config("enabled"):
                    continue

                await self._check_and_trigger()

            except asyncio.CancelledError:
                LOG.info(f"{self.name} 定时任务已停止")
                break
            except Exception as e:
                LOG.error(f"{self.name} 检查循环出错: {e}")

    async def _check_and_trigger(self):
        """检查所有群并触发暖群"""
        inactive_hours = self._float_config("inactive_hours", 4.0)
        cooldown_hours = self._float_config("cooldown_hours", 2.0)
        min_messages = self._int_config("min_messages_threshold", 5)

        current_time = time.time()

        # ✅ 遍历副本避免RuntimeError
        for group_id, last_active in list(self.group_last_active.items()):
            inactive_seconds = current_time - last_active
            inactive_time = inactive_seconds / 3600

            if inactive_time < inactive_hours:
                continue

            check_hours = inactive_hours + 24
            recent_msg_count = await self._get_recent_message_count(
                group_id, hours=check_hours
            )

            if recent_msg_count < min_messages:
                LOG.debug(f"群 {group_id} 历史消息不足({recent_msg_count} < {min_messages})，跳过暖群")
                continue

            last_trigger = await self._get_last_trigger(group_id)
            if last_trigger and (current_time - last_trigger) < (cooldown_hours * 3600):
                LOG.debug(f"群 {group_id} 还在冷却中，跳过暖群")
                continue

            trigger_prob = self._float_config("trigger_probability", 1.0)
            if random.random() > trigger_prob:
                continue

            await self._trigger_warm_message(group_id)
            await self._set_last_trigger(group_id, current_time)
            # ✅ 修复4: 更新群活跃时间
            self.group_last_active[group_id] = current_time

    async def _get_recent_message_count(self, group_id: str, hours: float) -> int:
        """获取指定时间段内的消息数量"""
        messages = await dao.get_messages_by_time_range(group_id, hours)
        return len(messages)

    async def _get_last_trigger(self, group_id: str) -> Optional[float]:
        """获取上次触发暖群的时间"""
        key = f"warmgroup_last_trigger_{group_id}"
        data = await dao.get_key(key)
        if data:
            try:
                return float(data)
            except ValueError:
                return None
        return None

    async def _set_last_trigger(self, group_id: str, timestamp: float):
        """设置上次触发暖群的时间"""
        key = f"warmgroup_last_trigger_{group_id}"
        await dao.set_key(key, str(timestamp))

    async def _trigger_warm_message(self, group_id: str):
        """触发暖群消息"""
        try:
            LOG.info(f"群 {group_id} 触发暖群消息")

            async with self._session_lock:
                message = await self._generate_warm_message()

            if message and not message.startswith("❌"):
                await self.api.post_group_msg(group_id=group_id, text=message)
                LOG.info(f"群 {group_id} 暖群消息已发送: {message[:30]}...")
            else:
                fallback_messages = [
                    "大家好呀！最近有什么好玩的事吗？😊",
                    "有人在线吗？聊聊天呗~",
                    "今天过得怎么样？有什么想分享的吗？",
                    "猜猜我现在在想什么？🤔",
                    "大家最近在追什么剧/玩什么游戏吗？",
                    "如果中了500万，你们会怎么花？💰"
                ]
                fallback_msg = random.choice(fallback_messages)
                await self.api.post_group_msg(group_id=group_id, text=fallback_msg)
                LOG.info(f"群 {group_id} 使用备用消息")

        except Exception as e:
            LOG.error(f"群 {group_id} 暖群消息生成失败: {e}")

    async def _generate_warm_message(self) -> str:
        """生成暖群消息"""
        try:
            messages = [
                {"role": "system", "content": self.config.get("warm_prompts", "")},
                {"role": "user", "content": "请生成一个暖场话题。"}
            ]

            message = await self.ai_core.get_ai_response(messages)
            return message
        except Exception as e:
            LOG.error(f"生成暖群消息失败: {e}")
            return ""

    async def on_close(self):
        """插件卸载时清理资源"""
        LOG.info(f"卸载 {self.name}")

        if hasattr(self, 'hid_group_msg'):
            self.unregister_handler(self.hid_group_msg)

        if hasattr(self, 'task'):
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        if hasattr(self, '_session_lock'):
            async with self._session_lock:
                if self.ai_core and hasattr(self.ai_core, 'session'):
                    await self.ai_core.session.close()


__all__ = ["WarmGroupPlugin"]