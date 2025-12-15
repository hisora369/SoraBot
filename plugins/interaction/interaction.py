import time
import random
from ncatbot.plugin_system import NcatBotPlugin, filter_registry
from ncatbot.plugin_system.event import NcatBotEvent
from ncatbot.core.event import GroupMessageEvent, PrivateMessageEvent, PokeNoticeEvent
from ncatbot.utils import get_log
from ncatbot.plugin_system import on_group_poke

LOG = get_log("Interaction")


class InteractionPlugin(NcatBotPlugin):
    name = "InteractionPlugin"
    version = "1.0.0"
    description = "用于处理与用户的直接对话和群组消息的插件"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 戳一戳冷却时间字典
        self.poke_cooldown = {}
        # 冷却时间（秒）
        self.COOLDOWN_SECONDS = 2

        # 群聊复读状态存储：{group_id: {"last_msg": str, "count": int, "replied": bool}}
        self.group_repeat_state = {}

    async def on_load(self) -> None:
        LOG.info(f"插件 {self.name} 加载成功")

        # 注册事件处理器
        self.hid1 = self.register_handler("ncatbot.private_message_event", self.on_private_message)
        self.hid2 = self.register_handler("ncatbot.group_message_event", self.on_group_message)
        self.hid3 = self.register_handler("ncatbot.notice_event", self.handle_poke)

    async def on_private_message(self, event: NcatBotEvent):
        """处理私聊消息"""
        if isinstance(event.data, PrivateMessageEvent):
            if event.data.raw_message == "测试" and event.data.sender.user_id == "2739879393":
                await event.data.reply("日日的空以成功启动")

    async def on_group_message(self, event: NcatBotEvent):
        """处理群聊消息"""
        if isinstance(event.data, GroupMessageEvent):
            if event.data.raw_message == "测试" and event.data.sender.user_id == "2739879393":
                await event.data.reply("日日的空以成功启动")

            # 检查复读逻辑
            await self._check_repeat_message(event.data)

    async def _check_repeat_message(self, event: GroupMessageEvent):
        """检查并处理群聊消息复读"""
        group_id = event.group_id
        message = event.raw_message.strip()

        # 忽略空消息
        if not message:
            return

        # 忽略机器人自己发送的消息，防止无限循环
        if event.sender.user_id == event.self_id:
            return

        # 初始化该群的状态
        if group_id not in self.group_repeat_state:
            self.group_repeat_state[group_id] = {
                "last_msg": message,
                "count": 1,
                "replied": False  # 标记是否已经复读过一次
            }
            LOG.debug(f"群 {group_id} 初始化复读状态: {message}")
            return

        # 获取当前状态
        state = self.group_repeat_state[group_id]

        # 检查是否与上一条消息相同
        if message == state["last_msg"]:
            state["count"] += 1

            # 当连续两条相同消息且尚未复读时触发复读
            if state["count"] == 2 and not state["replied"]:
                LOG.info(f"群 {group_id} 检测到连续相同消息，开始复读: {message}")

                try:
                    # 发送复读消息（使用指定的API方式）
                    await self.api.post_group_msg(group_id, text=message)
                    LOG.info(f"群 {group_id} 复读成功: {message}")

                    # 标记已复读，避免后续重复触发
                    state["replied"] = True

                except Exception as e:
                    LOG.error(f"复读发送失败: {e}")
                    # 即使失败也要标记，避免重复尝试
                    state["replied"] = True
        else:
            # 消息不同，重置状态
            self.group_repeat_state[group_id] = {
                "last_msg": message,
                "count": 1,
                "replied": False  # 重置复读标记
            }
            LOG.debug(f"群 {group_id} 消息更新: {message} (计数: 1)")

    async def handle_poke(self, event: NcatBotEvent):
        """处理群聊戳一戳事件"""
        # 默认回复消息列表
        DEFAULT_MESSAGES = [
            "喵~别戳我啦！",
            "哎呀，好痒！😊",
            "再戳我就要生气啦！",
            "戳我干啥呀？想我了吗？",
            "轻点戳，疼~",
            "嘿嘿，被发现了！",
            "戳一下，开心一整天~",
            "Stop poking me! Meow~",
            "戳我可以， but 请给我小鱼干🐟",
            "再戳我就掉毛啦！",
            "哎呀，不要戳脸脸！",
            "戳我10次有惊喜哦（骗你的）",
            "你戳到我痒痒肉啦！",
            "本喵正在忙，稍后再戳~",
            "戳一下，经验+1"
        ]

        # 验证是否是戳机器人自己
        if event.data.target_id != "1286149997":
            LOG.debug(f"忽略戳其他用户的事件: {event.data.target_id}")
            return

        user_id = event.data.user_id
        current_time = time.time()

        # 检查冷却时间
        if user_id in self.poke_cooldown:
            last_poke_time = self.poke_cooldown[user_id]
            time_diff = current_time - last_poke_time

            if time_diff < self.COOLDOWN_SECONDS:
                LOG.debug(f"用户 {user_id} 戳得太频繁，忽略 (间隔 {time_diff:.1f}s)")
                return

        # 更新最后戳的时间
        self.poke_cooldown[user_id] = current_time

        # 获取随机消息
        message = random.choice(DEFAULT_MESSAGES)

        # 发送回复
        try:
            await self.api.post_group_msg(event.data.group_id, text=message)
            LOG.info(f"用户 {user_id} 戳了机器人，回复: {message[:20]}...")
        except Exception as e:
            LOG.error(f"发送回复失败: {e}")


__all__ = ["InteractionPlugin"]