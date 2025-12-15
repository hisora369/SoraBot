import asyncio
import time
import jwt  # 确保 jwt 库已安装
import aiohttp
import csv
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

# 假设这个是同级目录下的模块
from .gen_jwt import generate_jwt

# 导入 NcatBot 插件相关
from ncatbot.plugin_system import NcatBotPlugin, command_registry, group_filter, admin_filter
from ncatbot.plugin_system import param
from ncatbot.core.event import BaseMessageEvent, GroupMessageEvent
from ncatbot.utils import get_log
from plugins.sys.core import dao

LOG = get_log("WeatherPlugin")


class WeatherPlugin(NcatBotPlugin):
    name = "WeatherPlugin"
    version = "1.1.1"
    description = "天气查询和定时播报插件(CSV版)"

    # 插件配置项
    DEFAULT_CONFIG = {
        "api_host": "ng76x8yu9q.re.qweatherapi.com",
        "jwt_token": "eyJhbGciOiJFZERTQSIsImtpZCI6IlQ2QjhFMlRSUTIiLCJ0eXAiOiJKV1QifQ.eyJpYXQiOjE3NjU2NTIxOTMsImV4cCI6MTc2NTY1MzEyMywic3ViIjoiNEtLUTdUMkJHQSJ9.P0xUgjoH7MP7w0_ustlwkvsur5gF9YHtRqSHNsaxtzzu6G7C52ihjSHAnKRlqMGaeKM-QPu77fJOy4cP83-uCQ",
        # 确保这里是正确的初始 Token
        "cities": ["北京", "上海", "广州"],
        "broadcast_time": "04:44",
        "cost_per_query": 5,
        "csv_filename": "China-City-List-latest.csv",
        "enabled_broadcast_groups": []  # 🔴 新增：用于存储已启用定时播报的群号(未来可能要迁移到数据库里面去)
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.city_map: Dict[str, str] = {}

    async def on_load(self):
        """插件加载时初始化"""
        LOG.info(f"加载 {self.name} v{self.version}")

        for key, value in self.DEFAULT_CONFIG.items():
            self.register_config(key, value)

        self.load_city_data()

        if not self.config.get("jwt_token"):
            LOG.warning("WeatherPlugin: ⚠️ 请在插件配置中设置 jwt_token")

        broadcast_time = self.config.get("broadcast_time", "08:00")
        self.add_scheduled_task(
            self.daily_weather_broadcast,
            "daily_weather_broadcast",
            broadcast_time,
            max_runs=None
        )

        await self._register_commands()

        LOG.info(f"{self.name} 加载完成，内存中城市数据: {len(self.city_map)} 条")

    async def on_close(self):
        LOG.info(f"卸载 {self.name}")

    def load_city_data(self):
        """从 CSV 文件加载城市数据"""
        filename = self.config.get("csv_filename", "China-City-List-latest.csv")

        # 尝试寻找文件的位置 (使用您原有的逻辑)
        possible_paths = [
            Path("data") / filename,
            Path("config/data") / filename,
            Path(__file__).parent / filename,
            Path(filename)
        ]

        csv_path = None
        for p in possible_paths:
            if p.exists():
                csv_path = p
                break

        if not csv_path:
            LOG.error(f"❌ 未找到城市列表文件: {filename}。请将其放入 data 目录。")
            return

        try:
            with open(csv_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)

                if reader.fieldnames:
                    fieldnames = [name.strip() for name in reader.fieldnames]
                    reader.fieldnames = fieldnames
                else:
                    LOG.error("❌ CSV 文件似乎为空或无法读取表头")
                    return

                count = 0
                for row in reader:
                    name = row.get("Location_Name_ZH", "").strip()
                    loc_id = row.get("Location_ID", "").strip()

                    if name and loc_id:
                        self.city_map[name] = loc_id
                        count += 1

                if count == 0:
                    LOG.warning(f"⚠️ 文件已读取但未匹配到数据。检测到的表头: {reader.fieldnames}")
                else:
                    LOG.info(f"成功从 {csv_path} 加载了 {count} 个城市数据")

        except Exception as e:
            LOG.error(f"读取 CSV 文件失败: {e}")

    # ---------------------------------------------------------------------
    # 核心修复：JWT 检查与刷新逻辑
    # ---------------------------------------------------------------------

    async def generate_jwt(self, force_refresh: bool = False) -> str:
        """
        获取一个有效的 JWT Token。
        如果配置中的 Token 过期、无效或不存在，则自动调用生成器生成新的。
        """

        token = self.config.get("jwt_token", "")
        # 打印调试信息，确认是否每次都读取到空值
        LOG.info(f"DEBUG: Token 状态: {'[EMPTY]' if not token else '[LOADED]'}")

        refresh_needed = force_refresh

        # 1. 检查 Token 是否需要刷新
        if not refresh_needed:
            if not token:
                # Case 1: Token 不存在或为空
                LOG.info("检测到 jwt_token 为空，需要生成新的 Token。")
                refresh_needed = True
            else:
                # Case 2: Token 存在，检查是否过期/格式是否正确
                try:
                    # 解析 Token 的载荷
                    payload = jwt.decode(
                        token,
                        options={"verify_signature": False},  # 忽略签名验证，仅读取 exp
                        algorithms=["EdDSA"]
                    )

                    exp_time = payload.get('exp', 0)
                    current_time = int(time.time())

                    # 提前 60 秒刷新 Token，防止 API 请求时过期
                    if exp_time - current_time < 60:
                        LOG.warning(f"检测到 JWT Token 即将过期 (剩余 {exp_time - current_time} 秒)，需要刷新。")
                        refresh_needed = True
                    else:
                        # Token 仍然有效
                        LOG.info("DEBUG: 状态 [LOADED] -> Token 有效，直接返回。")
                        return token

                except jwt.exceptions.DecodeError as e:
                    # Case 3: Token 格式错误 (如被截断、乱码等)
                    LOG.error(f"配置中的 JWT Token 格式错误或解析失败: {e}，将尝试生成新的 Token。")
                    refresh_needed = True
                except Exception as e:
                    LOG.error(f"检查 JWT 有效期时发生未知错误: {e}，将尝试刷新。")
                    refresh_needed = True

        # 2. 执行刷新操作（调用 gen_jwt.py）
        if refresh_needed:
            try:
                # 调用同级目录的生成函数
                new_token = generate_jwt()

                # 关键：更新插件配置对象 (这将等待框架自动保存到 YAML 文件)
                self.config["jwt_token"] = new_token

                LOG.info("✅ 已成功生成新的 JWT Token 并更新配置。")
                return new_token
            except Exception as e:
                LOG.error(f"❌ 动态生成 JWT 失败，请检查 gen_jwt.py 和 ed25519-private.pem: {e}")
                # 如果生成失败，抛出错误，阻止 API 调用
                raise Exception("无法获取有效的 JWT Token。")

                # 3. 既不需要刷新，也没有错误，返回现有 Token（如果它仍然是空值，则返回空）
        return token

    # ---------------------------------------------------------------------
    # API 调用相关
    # ---------------------------------------------------------------------

    async def get_weather(self, location_id: str, days: str = "3d") -> Optional[Dict]:
        try:
            # 🔴 调用自身的 generate_jwt 检查并获取 Token
            jwt_token = await self.generate_jwt()
            if not jwt_token:
                return None

            api_host = self.config.get("api_host", "ng76x8yu9q.re.qweatherapi.com")
            url = f"https://{api_host}/v7/weather/{days}"
            print(f"API URL: {url}")
            params = {"location": location_id}
            headers = {"Authorization": f"Bearer {jwt_token}"}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status != 200:
                        LOG.error(f"API HTTP Error: {response.status}")
                        return None
                    data = await response.json()
                    return data if data.get("code") == "200" else None
        except Exception as e:
            LOG.error(f"获取天气数据异常: {e}")
            return None

    # ---------------------------------------------------------------------
    # 其他命令和逻辑（保持不变）
    # ---------------------------------------------------------------------

    async def _register_commands(self):
        """注册命令"""

        @command_registry.command("weather", description="查询城市天气")
        @param(name="days", default=3, help="查询天数(1-7天)")
        async def weather_cmd(event: BaseMessageEvent, city: str, days: int = 3):
            await self.query_weather(event, city, days)

        @group_filter
        @admin_filter
        @command_registry.command("weather_cfg", description="管理天气配置")
        async def weather_cfg_cmd(event: GroupMessageEvent, action: str, parameter: str = ""):
            args = [parameter] if parameter else []
            await self.manage_config(event, action, *args)

        @command_registry.command("weather_coins", description="查看天气查询所需金币")
        async def weather_coins_cmd(event: BaseMessageEvent):
            cost = self.config.get("cost_per_query", 5)
            await event.reply(f"查询天气每次消耗 {cost} 金币")

    async def get_location_id(self, city_name: str) -> Optional[str]:
        # ... (保持不变)
        if not self.city_map:
            self.load_city_data()

        if city_name in self.city_map:
            return self.city_map[city_name]

        suffixes = ["市", "区", "县", "自治州", "地区"]
        cleaned_name = city_name
        for suffix in suffixes:
            if cleaned_name.endswith(suffix):
                cleaned_name = cleaned_name[:-len(suffix)]
                if cleaned_name in self.city_map:
                    return self.city_map[cleaned_name]
        return None

    def format_weather_message(self, city: str, weather_data: Dict) -> str:
        # ... (保持不变)
        if not weather_data or "daily" not in weather_data:
            return f"❌ 无法获取 {city} 的天气数据"

        daily_list = weather_data["daily"]
        messages = [f"🌤️ {city} 天气预报"]
        limit = min(len(daily_list), 15)

        for day in daily_list[:limit]:
            date = day["fxDate"]
            text_day = day["textDay"]
            text_night = day["textNight"]
            temp_max = day["tempMax"]
            temp_min = day["tempMin"]
            wind_dir = day["windDirDay"]

            msg = f"📅 {date}\n📝 {text_day}转{text_night}\n🌡️ {temp_min}°C ~ {temp_max}°C\n🌬️ {wind_dir}"
            messages.append(msg)

        return "\n\n".join(messages)

    async def query_weather(self, event: BaseMessageEvent, city: str, days: int = 3):
        # ... (保持不变)
        user_id = event.user_id
        location_id = await self.get_location_id(city)

        if not location_id:
            await event.reply(f"❌ 未找到城市 '{city}'")
            return

        if not days in [3, 7, 10, 15]:
            await event.reply("❌ 天数必须是3、7、10、15")
            return

        cost = int(self.config.get("cost_per_query", 5))
        user_info = await dao.get_user(user_id)

        if not user_info:
            await dao.add_exp_coin(user_id, exp=0, coin=0)
            user_info = await dao.get_user(user_id)

        if user_info.coin < cost:
            await event.reply(f"❌ 金币不足！需要 {cost}，当前 {user_info.coin}")
            return

        await dao.add_exp_coin(user_id, exp=0, coin=-cost)
        # await event.reply(f"⏳ 正在查询 {city} 天气...")

        weather_data = await self.get_weather(location_id, f"{days}d")

        if weather_data:
            await event.reply(self.format_weather_message(city, weather_data) + "\n\n" + f"查询成功！💰 本次查询消耗 {cost} 金币")
        else:
            await event.reply("❌ 获取失败，金币已退回")
            await dao.add_exp_coin(user_id, exp=0, coin=cost)

    async def manage_config(self, event: GroupMessageEvent, action: str, *args):
        """配置管理逻辑，现在包含启用/禁用定时播报。"""
        action = action.lower()
        current_group_id = event.group_id

        # 获取群聊列表（确保它是一个可操作的列表）
        enabled_groups = self.config.get("enabled_broadcast_groups", [])
        # 如果从 yaml 加载出来不是 list (例如 null)，则初始化为 list
        if not isinstance(enabled_groups, list):
            enabled_groups = []

        # --- 新增启用/禁用逻辑 ---

        if action == "enable":
            if current_group_id not in enabled_groups:
                enabled_groups.append(current_group_id)
                self.config["enabled_broadcast_groups"] = enabled_groups
                await event.reply("✅ 成功启用本群的每日天气定时播报功能！")
            else:
                await event.reply("⚠️ 本群已启用该功能，无需重复设置。")

        elif action == "disable":
            if current_group_id in enabled_groups:
                enabled_groups.remove(current_group_id)
                self.config["enabled_broadcast_groups"] = enabled_groups
                await event.reply("❌ 成功禁用本群的每日天气定时播报功能。")
            else:
                await event.reply("⚠️ 本群未启用该功能，无需禁用。")

        elif action == "status":
            if current_group_id in enabled_groups:
                await event.reply("✅ 本群的每日天气定时播报功能：**已启用**。")
            else:
                await event.reply("❌ 本群的每日天气定时播报功能：**已禁用**。")

        elif action == "add_city":
            if not args:
                await event.reply("❌ 请输入城市名")
                return
            city = args[0]
            if not await self.get_location_id(city):
                await event.reply(f"❌ 数据库中无此城市: {city}")
                return

            cities = self.config.get("cities", [])
            if city not in cities:
                cities.append(city)
                self.config["cities"] = cities
                await event.reply(f"✅ 已添加 {city}")
            else:
                await event.reply(f"⚠️ {city} 已在列表中")

        elif action == "remove_city":
            if not args:
                await event.reply("❌ 请输入城市名")
                return
            city = args[0]
            cities = self.config.get("cities", [])
            if city in cities:
                cities.remove(city)
                self.config["cities"] = cities
                await event.reply(f"✅ 已移除 {city}")
            else:
                await event.reply(f"⚠️ {city} 不在列表中")

        elif action == "list_cities":
            cities = self.config.get("cities", [])
            await event.reply(f"📋 当前城市: {', '.join(cities)}")

        elif action == "reload_csv":
            self.load_city_data()
            await event.reply(f"✅ 已重载 CSV，当前 {len(self.city_map)} 条数据")
        else:
            await event.reply("指令: add_city <城市>, remove_city <城市>, list_cities, reload_csv")

        # ------------------ 新增方法 ------------------

    async def _get_hourly_forecast_data(self, location_id: str) -> Optional[List[Dict]]:
        """
        调用和风天气 24小时逐小时天气预报 API (v7/weather/24h)。
        """
        try:
            # 1. 调用自身的 generate_jwt 检查并获取 Token
            jwt_token = await self.generate_jwt()
            if not jwt_token:
                LOG.error("获取 JWT Token 失败，无法查询逐小时天气。")
                return None

            # 2. 构造 API URL (使用 /v7/weather/24h 路径)
            api_host = self.config.get("api_host", "ng76x8yu9q.re.qweatherapi.com")
            url = f"https://{api_host}/v7/weather/24h"

            params = {"location": location_id}
            headers = {"Authorization": f"Bearer {jwt_token}"}

            # 3. 发起异步请求
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status != 200:
                        LOG.error(f"API HTTP Error (24h Forecast): {response.status}")
                        return None

                    data = await response.json()

                    # 4. 检查业务状态码并返回 hourly 数据
                    if data.get("code") == "200":
                        return data.get("hourly")  # 逐小时预报数据在 'hourly' 键下
                    else:
                        # 打印和风天气的业务错误信息
                        LOG.error(f"和风天气业务错误 (24h Forecast): {data.get('code')}, {data.get('msg')}")
                        return None

        except Exception as e:
            LOG.error(f"获取 24h 天气数据异常: {e}")
            return None

    def _format_hourly_broadcast(self, city: str, hourly_data: list) -> str:
        """
        处理 24 小时预报数据，总结为当日天气预报格式。
        """
        if not hourly_data:
            return f"【{city}】抱歉，未能获取24小时天气详情。"

        # 提取气温列表，并排除未来超过 24 小时的数据点 (通常 hourly 接口返回的是从当前时间开始的 24 个点)
        temps = [int(h['temp']) for h in hourly_data]
        min_temp = min(temps)
        max_temp = max(temps)

        # 选取一天中几个关键时段的数据点进行总结（假设定时播报是 08:00 左右）
        # 索引 0: 播报时 (约 08:00)
        # 索引 4: 中午 (约 12:00)
        # 索引 9: 傍晚 (约 17:00)

        # 确保索引在列表范围内
        morning_data = hourly_data[0]
        daytime_data = hourly_data[min(4, len(hourly_data) - 1)]
        evening_data = hourly_data[min(9, len(hourly_data) - 1)]

        # 计算白天的最大降水概率 (前10个数据点)
        daytime_pop = [int(h.get('pop', 0)) for h in hourly_data[:10]]
        max_pop = max(daytime_pop) if daytime_pop else 0
        pop_info = f"，降水概率 {max_pop}%" if max_pop > 0 else ""

        # 格式化输出
        summary = (
            f"【{city} 今日天气】\n"
            f"🌡️ 今日气温：{min_temp}°C (最低) ~ {max_temp}°C (最高)\n"
            f"----------------------------------\n"
            f"☀️ 上午 ({morning_data['temp']}°C)：{morning_data['text']}，{morning_data['windDir']}{morning_data['windScale']}级\n"
            f"🕛 中午 ({daytime_data['temp']}°C)：{daytime_data['text']}\n"
            f"🌙 傍晚 ({evening_data['temp']}°C)：{evening_data['text']}\n"
            f"🔔 提示：注意气温变化{pop_info}。"
        )
        return summary

    async def daily_weather_broadcast(self):
        cities = self.config.get("cities", [])
        # 🔴 获取已启用播报的目标群聊列表
        target_groups = self.config.get("enabled_broadcast_groups", [])

        if not cities or not target_groups:
            LOG.warning("定时播报未执行：未配置城市或当前无群聊启用。")
            return

        try:
            for group_id in target_groups:  # 🔴 只遍历已启用的群聊

                # 确保 group_id 是字符串（如果 NcatBot API 需要，否则保持 int）
                if isinstance(group_id, int):
                    group_id_str = str(group_id)
                else:
                    group_id_str = group_id

                msg_parts = ["📢 早上好，请查收今日天气播报"]
                for city in cities:
                    loc_id = await self.get_location_id(city)
                    if loc_id:
                        # 调用逐小时天气 API
                        hourly_data = await self._get_hourly_forecast_data(loc_id)

                        if hourly_data:
                            broadcast_msg = self._format_hourly_broadcast(city, hourly_data)
                            msg_parts.append(broadcast_msg)
                        else:
                            msg_parts.append(f"【{city}】天气获取失败。")

                if len(msg_parts) > 1:
                    # 3. 发送群消息
                    await self.api.post_group_msg(group_id_str, text="\n\n".join(msg_parts))
                    LOG.info(f"✅ 已向群 [{group_id_str}] 发送天气播报。")
        except Exception as e:
            LOG.error(f"定时播报任务执行错误: {e}")


__all__ = ["WeatherPlugin"]