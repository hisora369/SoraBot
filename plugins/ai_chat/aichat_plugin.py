import random
import time
from typing import Dict, List

from ncatbot.plugin_system import NcatBotPlugin, command_registry, NcatBotEvent
from ncatbot.core.event import BaseMessageEvent, PrivateMessageEvent, GroupMessageEvent
from ncatbot.utils import get_log, ncatbot_config
from ncatbot.utils.status import status
from .aichat_core import AIChatCore
from plugins.sys.core import dao
import json
import asyncio

LOG = get_log("AIChatPlugin")


class AIChatPlugin(NcatBotPlugin):
    """AI 聊天插件"""
    name = "AIChat"
    version = "1.0.0"
    description = "基于讯飞星火大模型的智能聊天插件"
    dependencies = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ai_core = None
        self._session_lock = asyncio.Lock()
        # ✅ 新增：群聊状态管理
        self.group_states = {}  # {group_id: {"last_reply_time": 0, "message_history": []}}
        # ✅ 新增：总结任务状态
        self.summary_tasks = {}  # {group_id: task_id}


    async def on_load(self):
        """插件加载时初始化"""
        LOG.info(f"加载 {self.name} v{self.version}")

        # 注册配置项
        self._register_default_configs()

        # 初始化 AI 核心
        config = self._load_ai_config()
        self.ai_core = AIChatCore(config)

        # 注册命令
        self._register_commands()

        # ✅ 新增：注册群聊消息处理器（用于@机器人触发）
        self.hid_group_msg = self.register_handler("ncatbot.group_message_event", self.on_group_message)

        # ✅ 注册定时总结任务
        if self._bool_config("summary_enabled"):
            self.add_scheduled_task(
                self._auto_summary_task,
                name=f"auto_summary_{self.name}",
                interval=f"{self._int_config('summary_auto_interval')}h",
                args=(None,)  # None 表示所有群
            )

        LOG.info(f"{self.name} 加载成功")

    def _register_default_configs(self):
        """注册默认配置项"""
        # ✅ 直接访问类属性，不依赖 self.ai_core
        default_config = AIChatCore.DEFAULT_CONFIG
        # API 配置
        self.register_config("api_key", "Bearer gwoOvnMxlStOJZQIQApq:PVFOxjBhXaNArYLcnnzS")
        self.register_config("api_url", default_config["api_url"])
        self.register_config("model", default_config["model"])

        # 长度限制配置
        self.register_config("max_history_length", default_config["max_history_length"])
        self.register_config("max_response_length", default_config["max_response_length"])
        self.register_config("max_input_length", default_config["max_input_length"])

        # 生成参数配置
        self.register_config("temperature", default_config["temperature"])
        self.register_config("top_k", default_config["top_k"])
        self.register_config("top_p", default_config["top_p"])
        self.register_config("max_tokens", default_config["max_tokens"])
        self.register_config("presence_penalty", default_config["presence_penalty"])
        self.register_config("frequency_penalty", default_config["frequency_penalty"])

        # 系统提示词
        self.register_config("system_prompt", default_config["system_prompt"])

        # 触发方式配置
        self.register_config("trigger_by_mention", True)  # 是否通过@Bot触发
        self.register_config("trigger_by_command", True)  # 是否通过/chat命令触发
        self.register_config("auto_reply_in_private", True)  # 私聊是否自动回复

        # 随机参与配置
        self.register_config("random_reply_probability", "0.1")  # 10% 概率
        self.register_config("random_reply_min_interval", "20")  # 60秒冷却
        self.register_config("topic_context_length", "10")  # 取最近10条消息
        self.register_config("random_reply_enabled", "true")  # 总开关

        # ✅ 新增：消息总结配置
        self.register_config("summary_enabled", "true")
        self.register_config("summary_auto_interval", "4")  # 4小时自动总结
        self.register_config("summary_time_range", "4")  # 总结过去4小时
        self.register_config("summary_min_messages", "10")  # 最少10条才总结
        self.register_config("summary_store_days", "7")  # 消息存储7天


    def _load_ai_config(self) -> dict:
        """加载 AI 配置"""
        return {
            "api_key": self.config.get("api_key", ""),
            "api_url": self.config.get("api_url", ""),
            "model": self.config.get("model", ""),
            # ✅ 数值配置项全部转换类型
            "max_history_length": int(self.config.get("max_history_length", 8000)),
            "max_response_length": int(self.config.get("max_response_length", 1000)),
            "max_input_length": int(self.config.get("max_input_length", 500)),
            "temperature": float(self.config.get("temperature", 1.3)),
            "top_k": int(self.config.get("top_k", 4)),
            "top_p": float(self.config.get("top_p", 0.8)),
            "max_tokens": int(self.config.get("max_tokens", 1024)),
            "presence_penalty": float(self.config.get("presence_penalty", 1.5)),
            "frequency_penalty": float(self.config.get("frequency_penalty", 1.0)),

            "system_prompt": self.config.get("system_prompt", ""),
        }

    def _register_commands(self):
        """注册聊天命令"""

        # @command_registry.command("chat", description="开始与 AI 对话")
        @command_registry.command("chat", aliases=["聊天"], description="与 AI 聊天")
        async def ai_chat_cmd(event: BaseMessageEvent, *text_parts: str):
            # 拼接用户输入
            user_input = " ".join(text_parts).strip()

            # 检查输入长度
            if len(user_input) > int(self.config.get("max_input_length", 500)):
                await event.reply(
                    f"❌ 输入过长（{len(user_input)}字），请控制在 {self.config.get('max_input_length', 500)} 字以内")
                return

            await self._handle_ai_chat(event, user_input)

        @command_registry.command("ai_clear", description="清空 AI 对话历史")
        @command_registry.command("清除记忆", description="清空对话历史")
        async def ai_clear_cmd(event: BaseMessageEvent):
            """清空用户的对话历史"""
            user_id = event.user_id
            key = self.ai_core.get_user_history_key(user_id)

            await dao.del_key(key)
            await event.reply("✅ 已清空对话历史")

        @command_registry.command("ai_config", description="查看 AI 配置")
        @command_registry.command("ai配置", description="查看 AI 配置")
        async def ai_config_cmd(event: BaseMessageEvent):
            """查看当前 AI 配置"""
            config_info = f"""🤖 AI 配置信息：
📌 API URL: {self.config.get('api_url', '未设置')}
🤖 模型: {self.config.get('model', '未设置')}
📏 历史长度限制: {self.config.get('max_history_length', 8000)}
📏 回复长度限制: {self.config.get('max_response_length', 1000)}
📏 输入长度限制: {self.config.get('max_input_length', 500)}
🌡️ Temperature: {self.config.get('temperature', 1.3)}
⚙️ Top K: {self.config.get('top_k', 4)}
⚙️ Top P: {self.config.get('top_p', 0.8)}
⚙️ Max Tokens: {self.config.get('max_tokens', 1024)}
"""
            await event.reply(config_info)

        # ✅ 新增：手动触发总结
        @command_registry.command("summary", aliases=["总结"], description="生成群聊总结")
        async def summary_cmd(event: BaseMessageEvent):
            """手动触发群聊总结"""
            if not self._bool_config("summary_enabled"):
                await event.reply("❌ 群聊总结功能未启用")
                return

            if not isinstance(event, GroupMessageEvent):
                await event.reply("⚠️ 此命令仅在群聊中可用")
                return

            await event.reply("🤖 正在生成群聊总结，请稍候...")
            await self._generate_and_send_summary(event.group_id)

    # def _register_message_handler(self):
    #     """注册消息处理器（自动触发）"""
    #
    #     @self.on_message
    #     async def handle_message(event: BaseMessageEvent):
    #         """处理消息，检测是否需要 AI 回复"""
    #
    #         # 检查是否启用自动回复
    #         if isinstance(event, PrivateMessageEvent):
    #             if not self.config.get("auto_reply_in_private", True):
    #                 return
    #         elif isinstance(event, GroupMessageEvent):
    #             # 群聊中只响应 @Bot 或 /ai 命令
    #             if not self._should_trigger_in_group(event):
    #                 return
    #
    #         # 提取消息内容
    #         message_text = self.ai_core.strip_ai_command(
    #             self._extract_message_text(event.message)
    #         )
    #
    #         # 如果消息为空（纯命令），不处理
    #         if not message_text:
    #             return
    #
    #         # 检查输入长度
    #         if len(message_text) > self.config.get("max_input_length", 500):
    #             return  # 私聊中不提示，避免骚扰
    #
    #         # 处理 AI 聊天
    #         await self._handle_ai_chat(event, message_text)

    async def on_group_message(self, event: NcatBotEvent):
        """监听所有群聊消息，检测@机器人并触发AI回复"""
        msg: GroupMessageEvent = event.data

        # ✅ 打印调试信息
        print(f"[AIChat] 收到群消息: raw={msg.raw_message}, self_id={msg.self_id}")

        # 检查是否需要触发
        if self._should_trigger_in_group(msg):
            print(f"[AIChat] 触发AI回复，用户输入: {msg.raw_message}")

            # 提取纯文本内容（移除@部分）
            user_input = self._extract_text_after_at(msg)

            if user_input.strip():
                await self._handle_ai_chat(msg, user_input.strip())
            else:
                await msg.reply("🤖 你好！我是Sora，可以问我任何问题。\n💡 使用 `/chat 你的问题` 或@我直接提问")

            return

        # 2. ✅ 新增：随机触发逻辑
        await self._try_random_reply_in_group(msg)

        # ✅ 存储消息（用于后续总结）
        if self._bool_config("summary_enabled"):
            await dao.store_group_message(
                group_id=msg.group_id,
                user_id=msg.user_id,
                nickname=msg.sender.nickname,
                message=msg.raw_message
            )

    async def _auto_summary_task(self, group_id: str = None):
        """自动总结任务"""
        if group_id:
            # 总结指定群
            await self._generate_and_send_summary(group_id)
        else:
            # 总结所有活跃的群
            for gid in self.group_states.keys():
                await self._generate_and_send_summary(gid)

    async def _generate_and_send_summary(self, group_id: str):
        """生成并发送群聊总结"""
        try:
            # 获取消息
            messages = await dao.get_messages_by_time_range(
                group_id,
                self._float_config("summary_time_range")
            )

            # 检查消息数量
            min_msgs = self._int_config("summary_min_messages")
            if len(messages) < min_msgs:
                LOG.info(f"群 {group_id} 消息数不足({len(messages)} < {min_msgs})，跳过总结")
                return

            # 构建 AI prompt
            prompt = self._build_summary_prompt(messages)

            # 调用 AI
            async with self._session_lock:
                summary = await self.ai_core.get_ai_response([
                    {"role": "system", "content": prompt}
                ])

            # 发送总结
            if summary and not summary.startswith("❌"):
                await self.api.post_group_msg(
                    group_id,
                    text=f"📊 群聊总结（过去{self._int_config('summary_time_range')}小时）：\n\n{summary}"
                )

                # 清理旧消息
                await dao.cleanup_old_messages(
                    group_id,
                    self._int_config("summary_store_days")
                )

        except Exception as e:
            LOG.error(f"群 {group_id} 总结失败: {e}")

    def _build_summary_prompt(self, messages: List[dict]) -> str:
        """构建总结 prompt"""

        # 格式化消息记录
        message_lines = []
        for msg in messages:
            time_str = time.strftime('%H:%M', time.localtime(msg["timestamp"]))
            message_lines.append(f"[{time_str}] {msg['nickname']}: {msg['message']}")

        message_text = "\n".join(message_lines)

        return f"""请分析以下群聊记录，生成一份群聊总结报告：

    {message_text}

    要求：
    1. **核心话题**：提炼出2-3个主要讨论话题
    2. **活跃时段**：指出聊得最热烈的时间段
    3. **参与情况**：列出最活跃的3-5位成员及其贡献
    4. **聊天氛围**：简要描述整体氛围（轻松/热烈/严肃等）
    5. **亮点金句**：摘录1-2条有趣或有深度的发言
    6. **格式清晰**：使用 emoji 和分点符号，便于阅读
    7. **长度适中**：总结控制在200-300字

    请用轻松、活泼的语气生成这份总结，就像在和朋友分享群聊趣事一样。"""



    async def _try_random_reply_in_group(self, event: GroupMessageEvent):
        """尝试随机参与群聊对话"""

        # 检查总开关
        if not self._bool_config("random_reply_enabled"):
            return

        group_id = event.group_id

        # 初始化群状态
        if group_id not in self.group_states:
            self.group_states[group_id] = {
                "last_reply_time": 0,
                "message_history": []
            }

        state = self.group_states[group_id]

        # 检查冷却时间
        current_time = time.time()
        min_interval = self._int_config("random_reply_min_interval")
        if current_time - state["last_reply_time"] < min_interval:
            return  # 还在冷却中

        # 检查概率
        probability = self._float_config("random_reply_probability")
        if random.random() > probability:
            return  # 没触发

        # ✅ 使用 API 收集完整上下文
        context = await self._collect_topic_context(event)

        # 更新最后回复时间
        state["last_reply_time"] = time.time()

        # 调用 AI 生成参与性回复
        await self._generate_participation_reply(event, context)

    async def _collect_topic_context(self, event: GroupMessageEvent) -> str:
        """
        使用 API 拉取群聊历史消息构建话题上下文
        """
        try:
            # 向后拉取最近 N 条消息（包含当前消息）
            count = self._int_config("topic_context_length")
            print(f"Collecting context for {count} messages")

            # ⚠️ 注意：需要 event 有 message_id 属性
            # 如果 event 没有 message_id，需要用其他方式获取
            history_messages_raw = await self.api.get_group_msg_history(
                event.group_id,
                # message_seq=1000,  # 假设 event 有 message_id
                count=count,
            )
            print(f"Received {len(history_messages_raw)} messages")
            # print(history_messages_raw)

            history_messages = []

            # for msg in history_messages_raw:
            #     print(f"处理消息: msg={msg}")
            #     if msg.sender.user_id != event.self_id:
            #         print("添加了一条消息")
            #         history_messages.append(msg.raw_message)  # 获取非机器人本身消息的文本内容

            # 格式化上下文
            context_parts = []
            for msg in history_messages_raw:
                # 跳过机器人自己的消息
                if msg.sender.user_id == event.self_id:
                    continue

                nickname = getattr(msg.sender, 'nickname', '未知用户')
                context_parts.append(f"{nickname}: {msg.raw_message}")

            # print(f"上下文: {context_parts}")

            return "\n".join(context_parts)

        except Exception as e:
            LOG.warning(f"获取群聊历史失败: {e}，降级为单条消息")
            # 降级方案：只使用当前消息
            nickname = getattr(event.sender, 'nickname', '未知用户')
            return f"{nickname}: {event.raw_message}"



    async def _generate_participation_reply(self, event: GroupMessageEvent, context: str):
        """生成参与性回复"""

        # 构建特殊的系统提示词
        participation_prompt = f"""你正在参与一个群聊对话，群友们正在讨论话题。总结历史消息，提炼先前的聊天主题。

    请给出一条 **简短、幽默、令人意想不到** 的回复，你的主要任务是 **在当前讨论中插科打诨，进行捣乱和转移注意力**。

    要求：
    1. 不要重复已经说过的内容。
    2. 语气要 **戏谑、跳脱、夸张**，像一个故意来搞怪的群友。
    3. 控制在30字以内。
    4. 不要加任何命令前缀。
    5. 回复内容必须是 **无关的烂梗、犀利的吐槽、无厘头的疑问，或突兀的感叹**，以达到打破当前严肃或正常讨论的效果。"""

        # 构建消息历史
        messages = [
            {"role": "system", "content": participation_prompt},
            # {"role": "user", "content": f"群友说: {event.raw_message}"}
        ]

        for his_msg in context.split("\n"):
            user_name, content = his_msg.split(":", 1)
            messages.append({"role": "user", "content": f"{content}"})

        print(f"History: {messages}")

        # 调用 AI
        async with self._session_lock:
            response = await self.ai_core.get_ai_response(messages)

        # 过滤掉可能的命令前缀
        response = response.strip()
        if response.startswith('/'):
            response = response[1:].strip()

        # 发送回复
        if response and not response.startswith("❌"):
            print(f"AI回复: {response}")
            await self.api.post_group_msg(event.group_id, text=response)
            LOG.info(f"群 {event.group_id} 随机参与回复: {response[:20]}...")

    def _bool_config(self, key: str, default: bool = False) -> bool:
        """安全获取布尔配置"""
        val = self.config.get(key, str(default).lower())
        if isinstance(val, str):
            return val.lower() == "true"
        return bool(val)

    def _int_config(self, key: str, default: int = 0) -> int:
        """安全获取整型配置"""
        try:
            return int(self.config.get(key, default))
        except (ValueError, TypeError):
            return default

    def _float_config(self, key: str, default: float = 0.0) -> float:
        """安全获取浮点型配置"""
        try:
            return float(self.config.get(key, default))
        except (ValueError, TypeError):
            return default


    def _extract_text_after_at(self, event: GroupMessageEvent) -> str:
        """提取@机器人之后的文本内容"""
        import re

        # 移除@机器人的CQ码
        at_pattern = rf"\[CQ:at,qq={event.self_id}\]"
        text_without_at = re.sub(at_pattern, "", event.raw_message)

        # 清理多余的空格
        return text_without_at.strip()

    def _should_trigger_in_group(self, event: GroupMessageEvent) -> bool:
        """判断是否在群聊中触发 AI 回复"""
        print(f"[AIChat] 检查触发条件: raw_msg={event.raw_message}")

        # 检查是否被 @
        if self.config.get("trigger_by_mention", True):
            import re
            at_pattern = rf"\[CQ:at,qq={event.self_id}\]"
            if re.search(at_pattern, event.raw_message):
                print("[AIChat] ✅ 检测到@机器人")
                return True

        # 检查是否是 /chat 命令
        if self.config.get("trigger_by_command", True):
            if event.raw_message.startswith('/chat ') or event.raw_message == '/chat':
                print("[AIChat] ✅ 检测到/chat命令")
                return True

        print("[AIChat] ❌ 未满足触发条件")
        return False

    def _extract_message_text(self, message_array) -> str:
        """从消息数组中提取文本"""
        return "".join(seg.text for seg in message_array.filter_text())

    async def _handle_ai_chat(self, event: BaseMessageEvent, user_input: str):
        """处理 AI 聊天核心逻辑"""
        user_id = event.user_id
        user_nickname = getattr(event.sender, 'nickname', '用户')

        # ✅ 使用 self.ai_core.config 获取已转换的配置值
        if len(user_input) > self.ai_core.config["max_input_length"]:
            await event.reply(
                f"❌ 输入过长（{len(user_input)}字），请控制在 {self.ai_core.config['max_input_length']} 字以内")
            return

        # 获取用户历史记录
        history = await self._get_user_history(user_id)

        # 构建包含用户输入的消息列表
        messages = self.ai_core.build_messages(history, user_input)

        # 调用 AI API 获取回复
        async with self._session_lock:
            response = await self.ai_core.get_ai_response(messages)

        # 发送回复
        await event.reply(response)

        # 如果回复成功（不是错误信息），更新历史
        if not response.startswith("❌") and not response.startswith("⏰") and not response.startswith("⚠️"):
            # 添加 AI 回复到历史
            messages.append({
                "role": "assistant",
                "content": response
            })

            # 保存更新后的历史
            await self._save_user_history(user_id, messages)

            # 记录日志
            LOG.info(f"用户 {user_id}({user_nickname}) 的对话历史已更新")

    async def _get_user_history(self, user_id: str) -> List[Dict[str, str]]:
        """获取用户对话历史"""
        key = self.ai_core.get_user_history_key(user_id)
        history_data = await dao.get_key(key)

        if history_data:
            try:
                history = json.loads(history_data)
                # 确保包含 system prompt
                if not history or history[0].get("role") != "system":
                    system_prompt = {
                        "role": "system",
                        "content": self.config.get("system_prompt", "")
                    }
                    history.insert(0, system_prompt)
                return history
            except:
                pass

        # 没有历史记录，创建新的
        return [
            {
                "role": "system",
                "content": self.config.get("system_prompt", "")
            }
        ]

    async def _save_user_history(self, user_id: str, messages: List[Dict[str, str]]):
        """保存用户对话历史"""
        key = self.ai_core.get_user_history_key(user_id)

        # 裁剪历史
        trimmed_messages = self.ai_core._trim_history(messages)

        # 保存到数据库（设置7天过期）
        history_json = json.dumps(trimmed_messages, ensure_ascii=False)
        await dao.set_key_ttl(key, history_json, 7 * 24 * 3600)

    async def on_close(self):
        """插件卸载时清理资源"""
        LOG.info(f"卸载 {self.name}")

        # 注销事件处理器
        if hasattr(self, 'hid_group_msg'):
            self.unregister_handler(self.hid_group_msg)

        # ✅ 清理群聊状态
        self.group_states.clear()

        # 关闭 AI 会话
        if hasattr(self, '_session_lock'):
            await self._session_lock.acquire()
            if self.ai_core and hasattr(self.ai_core, 'session'):
                await self.ai_core.session.close()
            self._session_lock.release()