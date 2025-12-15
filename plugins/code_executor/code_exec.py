"""
CodeExecutor Plugin - 使用 Piston API 的安全远程代码执行插件
支持多种编程语言：Python, JavaScript, C, C++, Go, Rust 等
"""
import asyncio
import aiohttp
import time
from typing import Optional, Dict, List, Any
from ncatbot.plugin_system import NcatBotPlugin, command_registry, NcatBotEvent
from ncatbot.core.event import BaseMessageEvent
from ncatbot.utils import get_log
from uuid import UUID

LOG = get_log("CodeExecutor")

# Piston API 配置
PISTON_API_URL = "https://emkc.org/api/v2/piston/execute"
PISTON_RUNTIMES_URL = "https://emkc.org/api/v2/piston/runtimes"
PISTON_RUN_TIMEOUT = 15  # 请求超时时间（秒）
MAX_OUTPUT_LENGTH = 1500  # 最大输出长度限制
MAX_CODE_LENGTH = 2000  # 最大代码长度限制
RATE_LIMIT_PER_USER = 3  # 每个用户每分钟的调用次数限制

# 备份配置（当无法从 API 获取时使用）
SUPPORTED_LANGUAGES_BACKUP = {
    "python": {"language": "python", "version": "3.10.0", "aliases": ["py", "python3"]},
    "javascript": {"language": "javascript", "version": "18.15.0", "aliases": ["js", "node"]},
    "java": {"language": "java", "version": "15.0.2", "aliases": ["java"]},
    "c": {"language": "c", "version": "10.2.0", "aliases": ["c"]},
    "cpp": {"language": "cpp", "version": "10.2.0", "aliases": ["cpp", "c++", "cplusplus"]},
    "go": {"language": "go", "version": "1.16.2", "aliases": ["go", "golang"]},
    "rust": {"language": "rust", "version": "1.68.2", "aliases": ["rust", "rs"]},
}


class CodeExecutorPlugin(NcatBotPlugin):
    name = "CodeExecutor"
    version = "1.3.2"
    description = "使用 Piston API 的安全远程代码执行插件，支持多语言"
    author = "NcatBot"
    dependencies = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 用户调用频率限制：user_id -> [timestamp1, timestamp2, ...]
        self.user_rate_limits: Dict[str, List[float]] = {}
        self._run = True
        # 存储事件处理器ID，用于清理
        self._handler_ids: List[UUID] = []
        # 运行时缓存：动态获取并缓存可用的语言运行时
        self.runtimes_cache: Optional[List[Dict[str, Any]]] = None
        self.runtimes_cache_time: float = 0

    async def on_load(self):
        """插件加载时初始化"""
        LOG.info(f"{self.name} v{self.version} 加载成功")

        # 使用 register_handler 手动注册事件处理器
        self._handler_ids.append(
            self.register_handler("ncatbot.private_message_event", self._on_private_message)
        )
        self._handler_ids.append(
            self.register_handler("ncatbot.group_message_event", self._on_group_message)
        )

        # 启动定时清理任务
        self.task = asyncio.create_task(self._cleanup_rate_limits_loop())

        # 预加载运行时列表
        await self._fetch_runtimes()
        LOG.info(f"已注册 {len(self._handler_ids)} 个事件处理器")

        if self.runtimes_cache:
            languages = [r["language"] for r in self.runtimes_cache]
            LOG.info(f"从 Piston API 动态加载了 {len(languages)} 个语言运行时")

    async def on_close(self):
        """插件卸载时清理资源"""
        self._run = False

        # 保存处理器数量用于日志
        handler_count = len(self._handler_ids)

        # 注销所有事件处理器
        for handler_id in self._handler_ids:
            self.unregister_handler(handler_id)

        self._handler_ids.clear()

        # 取消定时任务
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass

        LOG.info(f"{self.name} 已卸载，已清理 {handler_count} 个事件处理器")

    async def _fetch_runtimes(self) -> Optional[List[Dict[str, Any]]]:
        """
        从 Piston API 获取可用的运行时列表并缓存
        缓存有效期：24小时
        """
        current_time = time.time()

        # 检查缓存是否有效（24小时内）
        if self.runtimes_cache and current_time - self.runtimes_cache_time < 86400:
            return self.runtimes_cache

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(PISTON_RUNTIMES_URL, timeout=10) as response:
                    response.raise_for_status()
                    data = await response.json()

                    # 验证数据结构
                    if isinstance(data, list) and len(data) > 0:
                        self.runtimes_cache = data
                        self.runtimes_cache_time = current_time
                        LOG.info(f"成功从 Piston API 获取 {len(data)} 个运行时")
                        return data
                    else:
                        LOG.warning(f"获取运行时列表返回了无效数据: {data}")
                        return None

        except Exception as e:
            LOG.error(f"获取 Piston 运行时列表失败: {e}", exc_info=True)
            # 返回缓存（即使过期也比没有好）
            return self.runtimes_cache

    async def _cleanup_rate_limits_loop(self):
        """定期清理过期的速率限制记录（每分钟执行一次）"""
        while self._run:
            await asyncio.sleep(60)
            current_time = time.time()
            for user_id, timestamps in list(self.user_rate_limits.items()):
                # 保留最近60秒内的调用记录
                self.user_rate_limits[user_id] = [
                    ts for ts in timestamps if current_time - ts < 60
                ]
                if not self.user_rate_limits[user_id]:
                    del self.user_rate_limits[user_id]

    def _check_rate_limit(self, user_id: str) -> bool:
        """检查用户是否超过速率限制"""
        current_time = time.time()

        if user_id not in self.user_rate_limits:
            self.user_rate_limits[user_id] = []

        # 清理过期的记录
        self.user_rate_limits[user_id] = [
            ts for ts in self.user_rate_limits[user_id]
            if current_time - ts < 60
        ]

        # 检查是否超过限制
        if len(self.user_rate_limits[user_id]) >= RATE_LIMIT_PER_USER:
            return False

        # 添加新的调用记录
        self.user_rate_limits[user_id].append(current_time)
        return True

    async def _on_private_message(self, event: NcatBotEvent):
        """私聊消息事件处理器（手动注册）"""
        LOG.debug(f"收到私聊消息: user_id={event.data.user_id}, message={event.data.raw_message}")

    async def _on_group_message(self, event: NcatBotEvent):
        """群聊消息事件处理器（手动注册）"""
        LOG.debug(f"收到群聊消息: group_id={event.data.group_id}, user_id={event.data.user_id}, message={event.data.raw_message}")

    async def _get_language_runtime(self, language: str) -> Optional[Dict[str, Any]]:
        """
        获取指定语言的运行时配置
        先从缓存中查找，如果没有则尝试动态获取
        """
        # 确保运行时列表已加载
        if not self.runtimes_cache:
            await self._fetch_runtimes()

        if not self.runtimes_cache:
            # 如果仍无法获取，使用硬编码备份
            LOG.warning("无法从 Piston API 获取运行时列表，使用内置备份配置")
            return SUPPORTED_LANGUAGES_BACKUP.get(language.lower())

        # 查找匹配的语言运行时
        language_lower = language.lower()
        for runtime in self.runtimes_cache:
            if (runtime["language"].lower() == language_lower or
                    language_lower in [alias.lower() for alias in runtime.get("aliases", [])]):
                return runtime

        return None

    async def _parse_language_and_code(self, first_arg: str, remaining_text: str) -> tuple[str, str]:
        """
        解析用户输入的语言和代码
        支持格式: /exec [语言] <代码>
        返回: (实际语言, 实际代码)
        """
        runtime = await self._get_language_runtime(first_arg)
        if runtime:
            return runtime["language"], remaining_text
        full_code = f"{first_arg} {remaining_text}".strip()
        return "python", full_code

    async def _call_piston_api(
            self,
            language: str,
            code_to_execute: str
    ) -> str:
        """
        调用 Piston API 执行代码

        Args:
            language: 编程语言
            code_to_execute: 要执行的代码

        Returns:
            格式化的执行结果字符串
        """
        if not code_to_execute.strip():
            return "❌ 请提供要执行的代码。"

        # 获取语言运行时配置
        runtime = await self._get_language_runtime(language)
        if not runtime:
            # 获取所有可用的语言列表
            if self.runtimes_cache:
                available_langs = [r["language"] for r in self.runtimes_cache]
                aliases_info = []
                for r in self.runtimes_cache:
                    if r.get("aliases"):
                        aliases_info.append(f"{r['language']}: {', '.join(r['aliases'])}")

                return (
                        f"❌ 不支持的语言: {language}\n"
                        f"可用语言: {', '.join(available_langs)}\n\n"
                        f"别名参考:\n" + "\n".join(aliases_info[:5]) +
                        ("..." if len(aliases_info) > 5 else "")
                )
            else:
                return f"❌ 不支持的语言: {language}，且无法获取可用语言列表。"

        version = runtime.get("version", "latest")
        language_actual = runtime["language"]

        LOG.info(f"执行代码: language={language_actual}, version={version}, length={len(code_to_execute)}")

        # 构造请求载荷
        payload = {
            "language": language_actual,
            "version": version,
            "files": [{"content": code_to_execute}]
        }

        try:
            start_time = time.time()

            async with aiohttp.ClientSession() as session:
                async with session.post(
                        PISTON_API_URL,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=PISTON_RUN_TIMEOUT)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

            end_time = time.time()

            # 安全获取运行数据
            run_data = data.get("run", {})
            if not run_data:
                LOG.error(f"Piston API 返回了无效的数据结构: {data}")
                return f"❌ Piston API 返回了无效的数据结构: {data.get('message', '未知错误')}"

            # 获取输出和错误
            output = run_data.get("output", "").strip()
            stderr = run_data.get("stderr", "").strip()

            # 截断过长的输出
            if len(output) > MAX_OUTPUT_LENGTH:
                output = (
                    f"{output[:MAX_OUTPUT_LENGTH]}\n"
                    f"... [输出内容过长（{len(output)}字符），已截断] ..."
                )

            # 安全获取运行时信息
            runtime_info = run_data.get("runtime", "unknown")
            execution_time = end_time - start_time

            # 格式化结果
            if stderr:
                # 有错误信息
                result_type = "运行时错误"
                if output:
                    output_content = f"stdout:\n{output}\n\nstderr:\n{stderr}"
                else:
                    output_content = stderr
            else:
                # 成功执行
                result_type = "执行结果"
                output_content = output if output else "(无输出)"

            return (
                f"✅ {result_type} (用时: {execution_time:.2f}s, 运行时: {runtime_info}):\n"
                f"```\n{output_content}\n```"
            )

        except aiohttp.ClientError as e:
            LOG.error(f"API 调用失败: {e}", exc_info=True)
            return f"❌ API 调用失败: 网络错误或超时 ({type(e).__name__})"
        except asyncio.TimeoutError:
            LOG.warning(f"请求超时（{PISTON_RUN_TIMEOUT}秒）")
            return (
                f"❌ 请求超时（{PISTON_RUN_TIMEOUT}秒）。\n"
                "可能原因：网络延迟、代码执行时间过长或无限循环。"
            )
        except Exception as e:
            LOG.error(f"Piston API 调用异常: {e}", exc_info=True)
            return f"❌ 执行失败: {str(e)}"

    @command_registry.command(
        "exec",
        aliases=["run", "code"],
        description="执行远程代码，支持多种编程语言"
    )
    async def execute_code_cmd(
            self,
            event: BaseMessageEvent,
            code_text: str
    ):
        """
        执行远程代码
        用法: /exec [语言] <代码>
        示例: /exec python print("Hello, World!")
        """
        # 速率限制检查
        if not self._check_rate_limit(event.user_id):
            await event.reply(
                f"❌ 调用过于频繁，请稍后再试。\n"
                f"每个用户每分钟最多执行 {RATE_LIMIT_PER_USER} 次。"
            )
            return

        # 长度检查
        if len(code_text) > MAX_CODE_LENGTH:
            await event.reply(
                f"❌ 代码长度超过限制 ({MAX_CODE_LENGTH} 字符)。\n"
                "请缩短代码长度。"
            )
            return

        # 空输入检查
        if not code_text.strip():
            await event.reply("❌ 请提供要执行的代码。")
            return

        # 更好的边界情况处理
        parts = code_text.split(maxsplit=1)
        if len(parts) == 2:
            first_word, remaining = parts
            language, actual_code = await self._parse_language_and_code(first_word, remaining)
        elif len(parts) == 1:
            # 检查是否是语言名
            runtime = await self._get_language_runtime(parts[0])
            if runtime:
                await event.reply(f"❌ 请提供要执行的 {runtime['language']} 代码。")
                return
            language = "python"
            actual_code = code_text
        else:
            await event.reply("❌ 请提供要执行的代码。")
            return

        # 执行代码
        result = await self._call_piston_api(language, actual_code)
        await event.reply(result)

    @command_registry.command("calc", description="执行数学计算")
    async def calculate_cmd(self, event: BaseMessageEvent, expression: str):
        """
        执行数学计算表达式
        用法: /calc <数学表达式>
        示例: /calc 1 + 2 * (3.14 ** 2)
        """
        # 速率限制检查
        if not self._check_rate_limit(event.user_id):
            await event.reply(
                f"❌ 调用过于频繁，请稍后再试。\n"
                f"每个用户每分钟最多执行 {RATE_LIMIT_PER_USER} 次。"
            )
            return

        # 长度检查
        if len(expression) > 500:
            await event.reply("❌ 表达式过长，请简化。")
            return

        # 空表达式检查
        if not expression.strip():
            await event.reply("❌ 请提供要计算的表达式。")
            return

        # 包装为包含 math 导入的 print() 语句
        code_to_execute = f"import math\nprint({expression})"

        # 执行计算
        result = await self._call_piston_api("python", code_to_execute)
        await event.reply(result)

    @command_registry.command("languages", description="查看支持的语言列表")
    async def list_languages_cmd(self, event: BaseMessageEvent):
        """显示所有支持的编程语言"""
        # 确保运行时列表已加载
        if not self.runtimes_cache:
            await self._fetch_runtimes()

        if not self.runtimes_cache:
            await event.reply("❌ 无法获取语言列表，请稍后重试。")
            return

        lang_list = []
        for runtime in self.runtimes_cache:
            lang = runtime["language"]
            version = runtime.get("version", "unknown")
            aliases = runtime.get("aliases", [])
            alias_str = f" (别名: {', '.join(aliases)})" if aliases else ""
            lang_list.append(f"- {lang} v{version}{alias_str}")

        await event.reply(
            "🚀 Piston API 支持的编程语言:\n" + "\n".join(lang_list[:15]) +
            ("\n..." if len(lang_list) > 15 else "") +
            "\n\n💡 使用 /exec [语言] <代码> 执行代码\n"
            "💡 使用 /calc <表达式> 进行计算"
        )

    @command_registry.command("exec_help", description="查看代码执行插件帮助")
    async def help_cmd(self, event: BaseMessageEvent):
        """显示帮助信息"""
        await event.reply(
            "🤖 代码执行插件帮助:\n\n"
            "📌 执行代码:\n"
            "  /exec python print('Hello, World!')\n"
            "  /exec js console.log('Hello from JavaScript')\n\n"
            "📌 数学计算:\n"
            "  /calc 1 + 2 * (3.14 ** 2)\n"
            "  /calc math.sqrt(16)\n\n"
            "📌 查看支持的语言:\n"
            "  /languages\n\n"
            "⚠️ 安全提示:\n"
            f"- 代码长度限制: {MAX_CODE_LENGTH} 字符\n"
            f"- 每分钟调用限制: {RATE_LIMIT_PER_USER} 次\n"
            "- 所有代码在远程沙箱中执行，不会危害本机\n"
            "- 语言版本自动更新，始终与 Piston API 同步"
        )


# 插件导出
__all__ = ["CodeExecutorPlugin"]