import json
import time
from typing import TypedDict, List, Dict, Optional, Tuple
import random
from ncatbot.core import BaseMessageEvent
from ncatbot.plugin_system import NcatBotPlugin, NcatBotEvent, command_registry, param
from ncatbot.core.event import GroupMessageEvent
from ncatbot.utils import get_log, OFFICIAL_GROUP_MESSAGE_EVENT
from plugins.game.game_base import BaseGamePlugin, GameState
from plugins.sys.core import dao  # 导入 DAO 单例
from plugins.game.combo_manager import ComboManager
LOG = get_log("ChengyuJielong")



class ChengyuManager:
    def __init__(self, json_file_path: str):
        """
        初始化成语管理器
        :param json_file_path: 成语JSON文件路径
        """
        self.json_file_path = json_file_path
        self.chengyu_dict: Dict[str, Dict] = {}  # 成语到完整信息的映射
        self.first_pinyin_index: Dict[str, List[str]] = {}  # 首字拼音->成语列表
        self.last_pinyin_index: Dict[str, List[str]] = {}  # 末字拼音->成语列表

        self._load_chengyu_data()

    def _load_chengyu_data(self):
        """加载成语数据并构建索引"""
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                chengyu_list = json.load(f)

            # 构建成语到完整信息的映射和拼音索引
            for item in chengyu_list:
                word = item["word"]
                self.chengyu_dict[word] = item

                # 构建首字拼音索引
                first_pinyin = item["first"]
                if first_pinyin not in self.first_pinyin_index:
                    self.first_pinyin_index[first_pinyin] = []
                self.first_pinyin_index[first_pinyin].append(word)

                # 构建末字拼音索引
                last_pinyin = item["last"]
                if last_pinyin not in self.last_pinyin_index:
                    self.last_pinyin_index[last_pinyin] = []
                self.last_pinyin_index[last_pinyin].append(word)

            LOG.info(f"✅ 加载成语 {len(self.chengyu_dict)} 条")

        except FileNotFoundError:
            LOG.error(f"❌ 文件不存在: {self.json_file_path}")
        except json.JSONDecodeError:
            LOG.error(f"❌ JSON解析错误: {self.json_file_path}")

    def get_chengyu_info(self, word: str) -> Optional[Dict]:
        """获取成语的完整信息"""
        return self.chengyu_dict.get(word)

    def get_first_last_pinyin(self, word: str) -> Optional[Tuple[str, str]]:
        """获取成语的首字拼音和末字拼音"""
        info = self.get_chengyu_info(word)
        if info:
            return info["first"], info["last"]
        return None

    def is_valid_chengyu(self, word: str) -> bool:
        """检查是否为有效成语"""
        return word in self.chengyu_dict

    def get_random_chengyu(self) -> Optional[str]:
        """随机获取一个成语"""
        if self.chengyu_dict:
            return random.choice(list(self.chengyu_dict.keys()))
        return None

    def get_chengyu_by_last_pinyin(self, pinyin: str) -> List[str]:
        """根据末字拼音获取可接龙的成语"""
        return self.first_pinyin_index.get(pinyin, [])


class ChengyuState(TypedDict):
    current_chengyu: str
    current_chengyu_last_pinyin: str
    used_chengyu: List[str]
    last_player: str
    player_stats: Dict[str, Dict]
    player_names: Dict[str, str]
    start_time: float
    player_combo: Dict[str, int]
    max_round: int  # ✅ 新增：游戏最大回合数

class ChengyuJielongPlugin(BaseGamePlugin[ChengyuState]):
    name = "成语接龙"
    version = "1.2"
    description = "成语接龙游戏，新增了最大回合数设定功能"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chengyu_manager = ChengyuManager('data/idiom.json')
        self.max_round = 8
        self.combo_manager = ComboManager(base_reward=5, combo_multiplier=1.5)

    def init_state(self) -> GameState[ChengyuState]:
        return GameState[ChengyuState](prefix="chengyu", ttl=86400)

    async def on_load(self) -> None:
        LOG.info(f"插件 {self.name} 加载成功")
        self.hid = self.register_handler("ncatbot.group_message_event", self.jielong)

    @command_registry.command("成语接龙")
    @param(name="rounds", default=8, help="游戏回合数（默认8轮）")
    async def start_jielong(self, event: BaseMessageEvent, rounds: int = 8):
        """开始成语接龙游戏"""
        if not isinstance(event, GroupMessageEvent):
            return await event.reply("⚠️ 该游戏只能在群聊中玩哦～")

        # ✅ 参数验证
        if rounds < 5 or rounds > 50:
            return await event.reply("❌ 回合数必须在 5-50 之间！")

        gid = event.group_id
        exist = await self.game_load(gid)
        if exist:
            return await event.reply("❌ 本群游戏进行中，直接参与即可！")

        first_chengyu = self.chengyu_manager.get_random_chengyu()
        if not first_chengyu:
            return await event.reply("❌ 成语库加载失败，无法开始游戏")

        pinyin_info = self.chengyu_manager.get_first_last_pinyin(first_chengyu)
        if not pinyin_info:
            return await event.reply("❌ 获取成语拼音失败")

        first_pinyin, last_pinyin = pinyin_info

        state = ChengyuState(
            current_chengyu=first_chengyu,
            current_chengyu_last_pinyin=last_pinyin,
            used_chengyu=[first_chengyu],
            last_player=event.user_id,
            player_stats={event.user_id: {"count": 0, "total_coins": 0}},
            start_time=time.time(),
            player_names={event.user_id: event.sender.card or event.sender.nickname or event.user_id},
            player_combo={},
            max_round=rounds,  # ✅ 新增：存储自定义回合数
        )

        await self.game_save(gid, state)

        chengyu_info = self.chengyu_manager.get_chengyu_info(first_chengyu)
        meaning = chengyu_info.get("explanation", "暂无释义") if chengyu_info else "暂无释义"
        if len(meaning) > 50:
            meaning = meaning[:50] + "..."

        await event.reply(
            f"🎉 成语接龙开始！\n"
            f"📖 起始成语：{first_chengyu}\n"
            f"📝 释义：{meaning}\n"
            f"🎯 下一位请以「{first_chengyu[-1]}」开头\n"
            f"   （拼音：{last_pinyin}）\n"
            f"📊 总回合数：{rounds} 轮"  # ✅ 显示实际设置的回合数
        )

    async def jielong(self, event: NcatBotEvent):
        """处理群消息接龙"""
        if not isinstance(event.data, GroupMessageEvent):
            return

        gid = event.data.group_id
        user_id = event.data.user_id
        text = event.data.raw_message.strip()

        state = await self.game_load(gid)
        if not state:
            return

        if "player_names" not in state:
            state["player_names"] = {}
        if "player_stats" not in state:
            state["player_stats"] = {}
        if "used_chengyu" not in state:
            state["used_chengyu"] = []
        if "player_combo" not in state:
            state["player_combo"] = {}

        if text.strip() == "[CQ:at,qq=1286149997] 不玩了":
            await self.end_game(gid)

        if len(text) != 4:
            return

        if not self.chengyu_manager.is_valid_chengyu(text):
            await event.data.reply(f"❌ {text} 不是有效成语！")
            return

        if text in state["used_chengyu"]:
            await event.data.reply(f"❌ {text} 已经用过了！")
            return

        new_pinyin_info = self.chengyu_manager.get_first_last_pinyin(text)
        if not new_pinyin_info:
            await event.data.reply(f"❌ 无法获取 {text} 的拼音信息！")
            return

        new_first_pinyin, new_last_pinyin = new_pinyin_info

        if new_first_pinyin != state["current_chengyu_last_pinyin"]:
            await event.data.reply(
                f"❌ 接龙失败！\n"
                f"上一个成语：{state['current_chengyu']}（末字拼音：{state['current_chengyu_last_pinyin']}）\n"
                f"必须以拼音【{state['current_chengyu_last_pinyin']}】开头！"
            )
            return

        sender = event.data.sender
        display_name = sender.card or sender.nickname or user_id

        last_player = state.get("last_player")
        if last_player and last_player != user_id:
            broken_combo = self.combo_manager.break_combo(last_player, state["player_combo"])
            if broken_combo > 0:
                LOG.info(f"玩家 {last_player} 连击中断（被 {user_id} 接替），中断前连击数: {broken_combo}")

            self.combo_manager.start_combo(user_id, state["player_combo"])
        else:
            self.combo_manager.continue_combo(user_id, state["player_combo"])

        current_combo = self.combo_manager.get_combo_count(user_id, state["player_combo"])
        this_reward = self.combo_manager.calculate_reward(user_id, state["player_combo"])

        state["used_chengyu"].append(text)
        state["current_chengyu"] = text
        state["current_chengyu_last_pinyin"] = new_last_pinyin
        state["last_player"] = user_id
        state["player_names"][user_id] = display_name

        if user_id not in state["player_stats"]:
            state["player_stats"][user_id] = {"count": 0, "total_coins": 0}

        state["player_stats"][user_id]["count"] += 1
        state["player_stats"][user_id]["total_coins"] += this_reward

        # ✅ 修复：立即将奖励写入数据库
        try:
            await dao.add_exp_coin(user_id, exp=0, coin=this_reward)
            LOG.info(f"✅ 玩家 {user_id} 获得 {this_reward} 金币奖励已发放到数据库")
        except Exception as e:
            LOG.error(f"❌ 发放金币失败: {e}")

        await self.game_save(gid, state)

        count = len(state["used_chengyu"])

        new_chengyu_info = self.chengyu_manager.get_chengyu_info(text)
        meaning = new_chengyu_info.get("explanation", "暂无释义") if new_chengyu_info else "暂无释义"
        if len(meaning) > 40:
            meaning = meaning[:40] + "..."

        combo_msg = ""
        if current_combo > 1:
            combo_msg = f"⚡ 连击×{current_combo}！"

        await event.data.reply(
            f"✅ 接龙成功！{combo_msg}\n"
            f"💰 本次获得 {this_reward} 金币\n"
            f"📖 {text}：{meaning}\n"
            f"📊 第 {count-1}/{self.max_round} 个成语\n"
            f"🎯 下一位请以「{text[-1]}」开头（拼音：{new_last_pinyin}）"
        )

        # 在 jielong 方法中修改结束判断
        if count >= state["max_round"]:  # ✅ 使用状态中的 max_round
            await self.end_game(gid)

    @command_registry.command("接龙排行")
    async def show_rank_cmd(self, event: BaseMessageEvent):
        """显示排行榜命令"""
        if not isinstance(event, GroupMessageEvent):
            return

        gid = event.group_id
        await self.show_rank(gid)

    async def show_rank(self, gid: str) -> None:
        """显示当前排行榜"""
        state = await self.game_load(gid)
        if not state:
            await self.api.post_group_msg(gid, text="❌ 本群暂无进行中的接龙游戏")
            return

        stats = state["player_stats"]
        names = state.get("player_names", {})
        combo_data = state.get("player_combo", {})

        if not stats:
            await self.api.post_group_msg(gid, text="📊 暂无玩家数据")
            return

        sorted_stats = sorted(stats.items(), key=lambda x: x[1]["total_coins"], reverse=True)
        rank_msg = "📊 接龙排行榜\n"
        for i, (qq, data) in enumerate(sorted_stats[:5], 1):
            name = names.get(qq, f"用户{qq}")
            count = data["count"]
            total_coins = data["total_coins"]
            combo_count = self.combo_manager.get_combo_count(qq, combo_data)
            combo_str = f" (连击×{combo_count})" if combo_count > 1 else ""
            rank_msg += f"{i}. {name} - {count} 次（💰{total_coins}金币）{combo_str}\n"

        rank_msg += "\n💡 金币已实时发放到账户"
        await self.api.post_group_msg(gid, text=rank_msg)

    async def end_game(self, gid: str) -> None:
        """结束游戏"""
        state = await self.game_load(gid)
        if not state:
            return

        stats = state["player_stats"]
        names = state.get("player_names", {})

        if stats:
            sorted_stats = sorted(stats.items(), key=lambda x: x[1]["total_coins"], reverse=True)
            rank_msg = "🏆 成语接龙最终榜\n"
            for i, (qq, data) in enumerate(sorted_stats[:5], 1):
                name = names.get(qq, f"用户{qq}")
                count = data["count"]
                total_coins = data["total_coins"]
                rank_msg += f"{i}. {name} - {count} 次（💰{total_coins}金币）\n"
            await self.api.post_group_msg(gid, text=rank_msg)

        await self.api.post_group_msg(gid, text="🎉 游戏结束！奖励已发放到各位账户～")
        await self.game_clear(gid)

__all__ = ["ChengyuJielongPlugin"]