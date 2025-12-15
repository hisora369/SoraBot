import asyncio
import random
import time
from typing import TypedDict, Dict, List, Optional
from ncatbot.core import BaseMessageEvent, GroupMessageEvent
from ncatbot.plugin_system import NcatBotPlugin, NcatBotEvent, command_registry, param, option
from ncatbot.utils import get_log, OFFICIAL_GROUP_MESSAGE_EVENT
from plugins.game.game_base import BaseGamePlugin, GameState
from plugins.game.combo_manager import ComboManager
from plugins.sys.core import dao, wordgame_dao
from plugins.sys.core import User

LOG = get_log("WordGuessing")


class WordGameState(TypedDict):
    current_word: str
    current_mask: List[bool]  # 每个位置是否已显示
    revealed_positions: int
    used_words: List[str]
    player_stats: Dict[str, Dict]
    player_combo: Dict[str, int]
    last_player: Optional[str]
    round_number: int
    max_rounds: int
    start_time: float
    hint_used: bool
    hints_revealed: Dict[str, bool]  # phonetic, definition
    difficulty: str
    strict_mode: bool
    player_names: Dict[str, str]


class WordGuessingPlugin(BaseGamePlugin[WordGameState]):
    name = "单词猜猜乐"
    version = "2.0.0"
    description = "多回合英语单词猜谜游戏，带连击加成和动态提示系统"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.max_rounds_default = 10
        self.time_limit = 100  # 每回合100秒
        self.hint_cost = 20  # 金币花费
        self.combo_manager = ComboManager(base_reward=10, combo_multiplier=1.5, combo_multiplier2=9.0)
        self.active_timers: Dict[str, asyncio.Task] = {}  # group_id -> timer task

    def init_state(self) -> GameState[WordGameState]:
        return GameState[WordGameState](prefix="wordgame", ttl=86400)




    async def on_load(self) -> None:
        LOG.info(f"插件 {self.name} 加载成功")
        # 注册事件处理器
        self.hid = self.register_handler(OFFICIAL_GROUP_MESSAGE_EVENT, self.handle_group_message)

    @command_registry.command("guess", description="开始单词猜谜游戏")
    @param(name="difficulty", default="normal", help="难度等级(easy/normal/hard/hell)")
    @option(short_name="s", long_name="strict", help="严格模式(必须完全拼写正确)")
    async def start_game(self, event: BaseMessageEvent, difficulty: str = "normal", strict: bool = False):
        """开始单词猜谜游戏"""
        if not isinstance(event, GroupMessageEvent):
            return await event.reply("⚠️ 该游戏只能在群聊中玩哦～")

        gid = event.group_id
        user_id = event.user_id

        # 验证难度
        valid_difficulties = ["easy", "normal", "hard", "hell"]
        if difficulty not in valid_difficulties:
            return await event.reply(f"❌ 无效难度！请选择: {', '.join(valid_difficulties)}")

        # 检查是否有进行中的游戏
        existing_state = await self.game_load(gid)
        if existing_state:
            return await event.reply("❌ 本群游戏进行中！使用 /猜不到 获取提示，或等待游戏结束")

        # 获取用户信息和金币
        user = await dao.get_user(user_id)
        if not user:
            user = User(qq=user_id, nick=event.sender.card or event.sender.nickname or user_id)

        # 创建新游戏状态
        state = WordGameState(
            current_word="",
            current_mask=[],
            revealed_positions=0,
            used_words=[],
            player_stats={},
            player_combo={},
            last_player=None,
            round_number=1,
            max_rounds=self.max_rounds_default,
            start_time=time.time(),
            hint_used=False,
            hints_revealed={"phonetic": False, "definition": False},
            difficulty=difficulty,
            strict_mode=strict,
            player_names={user_id: event.sender.card or event.sender.nickname or user_id}
        )

        await self.game_save(gid, state)



        await event.reply(
            f"🎮 单词猜猜乐开始！\n"
            f"📊 难度：{self._get_difficulty_name(difficulty)}\n"
            f"🎯 模式：{'严格模式' if strict else '普通模式'}\n"
            f"⏱️ 每回合 {self.time_limit} 秒\n"
            f"💰 提示花费：{self.hint_cost} 金币\n"
            f"⚡ 连续答对有连击加成！"
        )

        await asyncio.sleep(1)


        # 开始第一回合
        await self.start_new_round(gid)

    @command_registry.command("猜不到", aliases=["hint", "h"], description="花费金币获取提示")
    async def get_hint(self, event: BaseMessageEvent):
        """获取提示"""
        if not isinstance(event, GroupMessageEvent):
            return

        gid = event.group_id
        user_id = event.user_id

        state = await self.game_load(gid)
        if not state:
            return await event.reply("❌ 本群没有进行中的游戏")

        # 扣除金币
        user = await dao.get_user(user_id)
        if not user or user.coin < self.hint_cost:
            return await event.reply(f"❌ 金币不足！需要 {self.hint_cost} 金币")

        await dao.add_exp_coin(user_id, exp=0, coin=-self.hint_cost)

        # 显示一个随机字母
        word = state["current_word"]
        mask = state["current_mask"]

        # 找一个未显示的位置
        hidden_positions = [i for i, revealed in enumerate(mask) if not revealed]
        if not hidden_positions:
            return await event.reply("❌ 所有字母都已显示！")

        # 随机显示一个位置
        pos = random.choice(hidden_positions)
        mask[pos] = True
        state["revealed_positions"] += 1

        await self.game_save(gid, state)

        # 显示当前状态
        display_word = self._get_display_word(word, mask)
        await event.reply(
            f"💡 提示已使用 (-{self.hint_cost}金币)\n"
            f"📖 单词：{display_word}\n"
            f"🔤 已显示 {state['revealed_positions']}/{len(word)} 个字母"
        )

    async def handle_group_message(self, event: NcatBotEvent):
        """处理群消息"""
        if not isinstance(event.data, GroupMessageEvent):
            return

        gid = event.data.group_id
        user_id = event.data.user_id
        text = event.data.raw_message.strip().lower()

        # 检查是否有进行中的游戏
        state = await self.game_load(gid)
        if not state:
            return

        # 更新玩家名称
        if user_id not in state["player_names"]:
            state["player_names"][user_id] = event.data.sender.card or event.data.sender.nickname or user_id

        # 检查是否在等答案
        if not state["current_word"]:
            return

        # 检查是否是正确答案
        is_correct = False

        if state["strict_mode"]:
            # 严格模式：必须完全匹配
            is_correct = (text == state["current_word"].lower())
        else:
            # 普通模式：支持模糊匹配
            is_correct = (text == state["current_word"].lower())
            if not is_correct and len(text) >= 3:
                # 尝试模糊匹配（使用exchange字段）
                fuzzy_word = await wordgame_dao.get_word_by_fuzzy_match(text)
                if fuzzy_word and fuzzy_word["word"].lower() == state["current_word"].lower():
                    is_correct = True

        if not is_correct:
            return

        # 处理正确答案
        await self._handle_correct_answer(gid, user_id, state)

    async def _handle_correct_answer(self, gid: str, user_id: str, state: WordGameState):
        """处理正确答案"""
        word = state["current_word"]

        # 连击计算
        last_player = state["last_player"]
        if last_player and last_player != user_id:
            broken_combo = self.combo_manager.break_combo(last_player, state["player_combo"])
            if broken_combo > 0:
                LOG.info(f"玩家 {last_player} 连击中断（被 {user_id} 接替），中断前连击数: {broken_combo}")

            self.combo_manager.start_combo(user_id, state["player_combo"])
        else:
            self.combo_manager.continue_combo(user_id, state["player_combo"])

        current_combo = self.combo_manager.get_combo_count(user_id, state["player_combo"])
        reward = self.combo_manager.calculate_reward(user_id, state["player_combo"])

        # 更新统计
        if user_id not in state["player_stats"]:
            state["player_stats"][user_id] = {"count": 0, "total_coins": 0}

        state["player_stats"][user_id]["count"] += 1
        state["player_stats"][user_id]["total_coins"] += reward
        state["last_player"] = user_id

        # 发放奖励
        await dao.add_exp_coin(user_id, exp=5, coin=reward)

        # 显示结果
        word_info = await wordgame_dao.get_word_by_exact_match(word)
        meaning = word_info["translation"] if word_info else "暂无释义"

        combo_msg = ""
        if current_combo > 1:
            combo_msg = f"⚡ 连击×{current_combo}！"

        await self.api.post_group_msg(
            gid,
            text=f"🎉 恭喜 {state['player_names'][user_id]} 答对了！{combo_msg}\n"
                 f"📖 单词：{word}\n"
                 f"💬 释义：{meaning}\n"
                 f"💰 获得 {reward} 金币 + 5 经验"
        )

        # 进入下一回合或结束游戏
        state["round_number"] += 1
        await self.game_save(gid, state)  # 保存状态

        if state["round_number"] > state["max_rounds"]:
            await self._end_game(gid, state)
        else:
            await asyncio.sleep(2)
            await self.start_new_round(gid)


    async def start_new_round(self, gid: str):
        print(f"开始新回合 {gid}")
        """开始新回合"""
        state = await self.game_load(gid)
        if not state:
            return
        print(f"加载状态 {state}")

        # 取消旧计时器
        if gid in self.active_timers:
            self.active_timers[gid].cancel()
        print(f"取消计时器 {gid}")
        # 获取新单词
        word_data = await wordgame_dao.get_random_word(state["difficulty"])
        print(f"获取新单词 {word_data}")
        if not word_data:
            print(f"获取单词失败")
            await self.api.post_group_msg(gid, text="❌ 获取单词失败，游戏结束")
            print(f"清理游戏状态 {gid}")
            await self.game_clear(gid)
            print(f"清理完成")
            return
        print(f"获取单词 {word_data}")

        word = word_data["word"]

        # 防止重复单词
        if word in state["used_words"]:
            # 重试一次
            word_data = await wordgame_dao.get_random_word(state["difficulty"])
            if not word_data or word_data["word"] in state["used_words"]:
                await self.api.post_group_msg(gid, text="❌ 单词库不足，游戏结束")
                await self.game_clear(gid)
                return
            word = word_data["word"]

        state["current_word"] = word
        state["current_mask"] = [False] * len(word)
        state["revealed_positions"] = 0
        state["used_words"].append(word)
        state["hints_revealed"] = {"phonetic": False, "definition": False}
        state["hint_used"] = False
        state["start_time"] = time.time()

        await self.game_save(gid, state)

        # 显示单词掩码和中文释义
        display_word = "_" * len(word)
        await self.api.post_group_msg(
            gid,
            text=f"📚 第 {state['round_number']}/{state['max_rounds']} 回合\n"
                 f"🔤 单词：{display_word} ({len(word)} 字母)\n"
                 f"💬 释义：{word_data['translation']}\n"
                 f"⏱️ 限时 {self.time_limit} 秒"
        )

        # 启动计时器
        self.active_timers[gid] = asyncio.create_task(self._round_timer(gid, word_data))

    async def _round_timer(self, gid: str, word_data: dict):
        """回合计时器"""
        await asyncio.sleep(60)

        state = await self.game_load(gid)
        if not state or state["current_word"] != word_data["word"]:
            return

        # 显示音标提示
        if word_data["phonetic"] and not state["hints_revealed"]["phonetic"]:
            state["hints_revealed"]["phonetic"] = True
            await self.game_save(gid, state)
            await self.api.post_group_msg(
                gid,
                text=f"💡 时间提示 (60秒): 音标 [{word_data['phonetic']}]"
            )

        await asyncio.sleep(20)

        state = await self.game_load(gid)
        if not state or state["current_word"] != word_data["word"]:
            return

        # 显示英文释义提示
        if word_data["definition"] and not state["hints_revealed"]["definition"]:
            state["hints_revealed"]["definition"] = True
            await self.game_save(gid, state)
            definition = word_data["definition"]
            if len(definition) > 100:
                definition = definition[:100] + "..."
            await self.api.post_group_msg(
                gid,
                text=f"💡 时间提示 (80秒): 英文释义: {definition}"
            )

        await asyncio.sleep(20)

        state = await self.game_load(gid)
        if not state or state["current_word"] != word_data["word"]:
            return

        # 时间到，显示答案
        await self.api.post_group_msg(
            gid,
            text=f"⏰ 时间到！正确答案是: {word_data['word']}"
        )

        state["round_number"] += 1
        await self.game_save(gid, state)

        # ⭐ 关键修复：在调用 start_new_round 之前，先移除自己的引用
        # 这样 start_new_round 中的 cancel() 就不会取消到自己
        if gid in self.active_timers:
            del self.active_timers[gid]

        if state["round_number"] > state["max_rounds"]:
            await self._end_game(gid, state)
        else:
            await asyncio.sleep(3)
            await self.start_new_round(gid)
            print(f"开始新回合 {gid} 完成")

    def _get_display_word(self, word: str, mask: List[bool]) -> str:
        """获取显示的单词掩码"""
        result = []
        for i, char in enumerate(word):
            if mask[i]:
                result.append(char)
            else:
                result.append("_")
        return " ".join(result)

    def _get_difficulty_name(self, difficulty: str) -> str:
        """获取难度中文名"""
        names = {
            "easy": "简单",
            "normal": "一般",
            "hard": "困难",
            "hell": "地狱"
        }
        return names.get(difficulty, "未知")

    async def _end_game(self, gid: str, state: WordGameState):
        """结束游戏"""
        # 取消计时器
        if gid in self.active_timers:
            self.active_timers[gid].cancel()
            del self.active_timers[gid]

        # 生成排行榜
        if state["player_stats"]:
            sorted_stats = sorted(state["player_stats"].items(),
                                  key=lambda x: x[1]["total_coins"],
                                  reverse=True)

            rank_msg = "🏆 单词猜猜乐 最终榜单\n"
            for i, (qq, data) in enumerate(sorted_stats[:5], 1):
                name = state["player_names"].get(qq, f"用户{qq}")
                count = data["count"]
                total_coins = data["total_coins"]
                rank_msg += f"{i}. {name} - {count} 题（💰{total_coins}金币）\n"

            await self.api.post_group_msg(gid, text=rank_msg)

        await self.api.post_group_msg(gid, text="🎉 游戏结束！感谢大家的参与～")

        # 清理游戏状态
        await self.game_clear(gid)


__all__ = ["WordGuessingPlugin"]