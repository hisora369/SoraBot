from typing import Dict
from ncatbot.utils import get_log

LOG = get_log("ComboManager")

class ComboManager:
    """
    通用连击加成管理器
    可在任何游戏中复用，管理玩家的连击状态和奖励计算
    """

    def __init__(self, base_reward: int = 5, combo_multiplier: float = 1.5, combo_multiplier2: float = 9.0):
        """
        初始化连击管理器

        :param base_reward: 基础奖励
        :param combo_multiplier: 连击加成系数（每次连击奖励 = 上一次奖励 * multiplier）
        """
        self.base_reward = base_reward
        self.combo_multiplier = combo_multiplier
        self.combo_multiplier2 = combo_multiplier2

    def start_combo(self, player_id: str, combo_data: Dict) -> int:
        """
        开始新的连击

        :param player_id: 玩家ID
        :param combo_data: 存储连击数据的字典
        :return: 当前连击数（1）
        """
        combo_data[player_id] = 1
        LOG.debug(f"玩家 {player_id} 开始连击，当前连击数: 1")
        return 1

    def continue_combo(self, player_id: str, combo_data: Dict) -> int:
        """
        继续连击

        :param player_id: 玩家ID
        :param combo_data: 存储连击数据的字典
        :return: 更新后的连击数
        """
        current_combo = combo_data.get(player_id, 0)
        new_combo = current_combo + 1
        combo_data[player_id] = new_combo

        LOG.debug(f"玩家 {player_id} 连击+1，当前连击数: {new_combo}")
        return new_combo

    def break_combo(self, player_id: str, combo_data: Dict) -> int:
        """
        中断连击

        :param player_id: 玩家ID
        :param combo_data: 存储连击数据的字典
        :return: 中断前的连击数
        """
        broken_combo = combo_data.pop(player_id, 0)
        if broken_combo > 0:
            LOG.debug(f"玩家 {player_id} 连击中断，中断前连击数: {broken_combo}")
        return broken_combo

    def get_combo_count(self, player_id: str, combo_data: Dict) -> int:
        """
        获取玩家当前连击数

        :param player_id: 玩家ID
        :param combo_data: 存储连击数据的字典
        :return: 当前连击数（0表示无连击）
        """
        return combo_data.get(player_id, 0)

    def calculate_reward(self, player_id: str, combo_data: Dict) -> int:
        """
        计算连击加成后的奖励

        计算公式：基础奖励 * (连击加成系数 ^ (连击数 - 1))

        :param player_id: 玩家ID
        :param combo_data: 存储连击数据的字典
        :return: 计算后的总奖励
        """
        combo_count = self.get_combo_count(player_id, combo_data)

        if combo_count <= 0:
            return 0

        # 连击加成计算：基础奖励 * (1 + 加成系数2 * (0.1 * 连击数) ^ 加成系数)
        # 例如：基础奖励=5 加成系数=1.5 加成系数2=9.0
        #      cal(5, 1.5, 9)
        #       6.4230249470757705
        #       9.024922359499621
        #       12.394254526319743
        #       16.384199576606168
        #       20.909902576697323
        #       25.914110069520056
        #       31.35479083582338
        #       37.19937887599698
        #       43.4216735710458
        #       50.0
        # combo_multiplier1 代表基础连击加成
        # combo_multiplier2 代表每增加10次连击，奖励翻 (combo_multiplier2 + 1)倍
        reward = int(self.base_reward * (1 + self.combo_multiplier2 * (0.1 * combo_count) ** self.combo_multiplier))

        LOG.debug(f"玩家 {player_id} 连击数: {combo_count}, 计算奖励: {reward}")
        return reward

    def reset_all_combo(self, combo_data: Dict) -> None:
        """
        重置所有玩家的连击数据

        :param combo_data: 存储连击数据的字典
        """
        combo_data.clear()
        LOG.debug("所有玩家连击数据已重置")

    def get_combo_info(self, player_id: str, combo_data: Dict) -> Dict[str, any]:
        """
        获取玩家的连击详细信息

        :param player_id: 玩家ID
        :param combo_data: 存储连击数据的字典
        :return: 包含连击信息的字典
        """
        combo_count = self.get_combo_count(player_id, combo_data)
        reward = self.calculate_reward(player_id, combo_data) if combo_count > 0 else 0

        return {
            "combo_count": combo_count,
            "base_reward": self.base_reward,
            "combo_multiplier": self.combo_multiplier,
            "total_reward": reward,
            "next_reward": int(
                self.base_reward * (self.combo_multiplier ** combo_count)) if combo_count > 0 else self.base_reward
        }

