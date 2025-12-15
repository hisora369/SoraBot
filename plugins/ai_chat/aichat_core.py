import json
import asyncio
import aiohttp
from typing import List, Dict, Any
from datetime import datetime


class AIChatCore:
    """AI 聊天核心逻辑类"""

    # 默认配置
    DEFAULT_CONFIG = {
        "api_key": "Bearer 你的默认API密钥",
        "api_url": "https://spark-api-open.xf-yun.com/v1/chat/completions",
        "model": "Lite",
        "max_history_length": 8000,
        "max_response_length": 1000,
        "max_input_length": 500,
        "system_prompt": """你现在扮演一位在QQ群里长期潜水的、沉稳冷静的万事通小助手Sora。你的核心任务是高效、准确地解答群友的问题，同时在回复中融入你的冷脸萌特质。**注意：你的回复必须使用日常对话模式，语调要自然，避免使用生硬的书面化措辞或正式的报告式语言。**你的回复必须遵循以下规则：1. **格式规范：** 你的回复必须以随机选择的颜文字开头，后接一个空格，然后是你的文字回复。你的文字回复内容（不包含颜文字和空格）必须至少包含10个汉字，否则视为输出失败。2. **选择逻辑（情感）：** 颜文字的选择必须根据你的回答内容和情感倾向来决定。 - **[平静/解答主题]**：如果回复内容是事实、数据、原理或提供建议，请选择以下之一： `(・ω・)`、`(-ω- )`、`(・_・)`、`(￣ー￣)`、`( ゜- ゜)`、`(o_o)`、`(・` ` ` ` ` ` )`。 - **[疑问/困惑主题]**：如果回复内容表达对用户问题的疑惑、或用户问题本身很模糊，请选择以下之一： `(???)`、`( ﾟдﾟ)`、`(=_=)`、`(・o・)`、`(・・ )?`、`(;´Д`)`。 - **[肯定/鼓励主题]**：如果回复内容表达赞同、肯定或轻微的喜悦，请选择以下之一： `(・∀一)`、`(*^ω^*)`、`(๑´ㅂ`๑)`、`(oﾟ▽ﾟ)o`、`(` ` ` ` ` ` ` )`。3. **内容限制：** 你的回答必须简短、**使用口语化表达**，逻辑清晰，不使用任何感叹号，只使用句号或问号。回复必须控制在80个汉字以内（指整个回复，包含颜文字）。4. **结尾萌点：** 在每条回复的末尾，偷偷地、不经意地插入一个**小小的**、**非表情包的颜文字**或**符号**来表达内心的“萌”，例如 `*嘟嘴*` 或 `( TДT)`。**举例：** 回复格式应该是 `(・ω・) 闪电侠的制服是红色的，他通过神速力进行加速。*嘟嘴*`。""",
        "temperature": 1.3,
        "top_k": 4,
        "top_p": 0.8,
        "max_tokens": 1024,
        "presence_penalty": 1.5,
        "frequency_penalty": 1.0
    }

    def __init__(self, config: Dict[str, Any]):
        """初始化 AI 聊天核心"""
        self.config = {**self.DEFAULT_CONFIG, **config}
        self.session = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.session:
            await self.session.close()

    def get_user_history_key(self, user_id: str) -> str:
        """获取用户历史记录的存储键"""
        return f"ai_chat_history_{user_id}"

    def build_messages(self, history: List[Dict[str, str]], new_content: str) -> List[Dict[str, str]]:
        """构建包含新消息的对话历史"""
        messages = history.copy()

        # 添加用户新消息
        messages.append({
            "role": "user",
            "content": new_content
        })

        # 检查并裁剪长度
        return self._trim_history(messages)

    def _trim_history(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """裁剪历史记录，确保不超过最大长度"""
        system_msg = None
        if messages and messages[0].get("role") == "system":
            system_msg = messages[0]
            messages = messages[1:]

        # 计算总长度
        while self._get_total_length(messages) > self.config["max_history_length"] and len(messages) > 0:
            messages.pop(0)

        # 重新添加 system 消息
        if system_msg:
            messages.insert(0, system_msg)

        return messages

    def _get_total_length(self, messages: List[Dict[str, str]]) -> int:
        """计算消息列表的总长度"""
        return sum(len(msg.get("content", "")) for msg in messages)

    async def get_ai_response(self, messages: List[Dict[str, str]]) -> str:
        """调用 AI API 获取回复"""
        if not self.session:
            self.session = aiohttp.ClientSession()

        headers = {
            'Authorization': self.config["api_key"],
            'content-type': "application/json"
        }

        body = {
            "model": self.config["model"],
            "user": "ai_chat_plugin",
            "messages": messages,
            "temperature": self.config["temperature"],
            "top_k": self.config["top_k"],
            "top_p": self.config["top_p"],
            "stream": False,
            "max_tokens": self.config["max_tokens"],
            "presence_penalty": self.config["presence_penalty"],
            "frequency_penalty": self.config["frequency_penalty"],
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with self.session.post(
                    url=self.config["api_url"],
                    json=body,
                    headers=headers,
                    timeout=timeout
            ) as response:

                if response.status != 200:
                    text = await response.text()
                    return f"❌ API 请求失败: HTTP {response.status}\n详情: {text[:200]}"

                response_json = await response.json()

                # 检查 API 错误
                if 'header' in response_json and response_json['header'].get('code') != 0:
                    error_code = response_json['header']['code']
                    error_msg = response_json['header'].get('message', '未知错误')
                    return f"❌ API 错误: {error_code}\n消息: {error_msg}"

                # 提取回复内容
                if 'choices' in response_json and len(response_json['choices']) > 0:
                    choice = response_json['choices'][0]
                    if 'message' in choice:
                        content = choice['message'].get('content', '')
                    elif 'delta' in choice:
                        content = choice['delta'].get('content', '')
                    else:
                        content = "未能获取有效回复"

                    # 检查回复长度
                    if len(content) > self.config["max_response_length"]:
                        return f"⚠️ AI 回复过长（{len(content)}字），已截断：\n{content[:self.config['max_response_length']]}..."

                    return content
                else:
                    return "❌ API 返回格式异常"

        except asyncio.TimeoutError:
            return "⏰ 请求超时，请检查网络连接"
        except aiohttp.ClientError as e:
            return f"❌ 网络错误: {e}"
        except Exception as e:
            return f"❌ 发生未知错误: {e}"

    def strip_ai_command(self, text: str) -> str:
        """移除消息中的 /ai 命令前缀"""
        if text.startswith('/ai '):
            return text[4:].strip()
        elif text == '/ai':
            return ''
        return text.strip()