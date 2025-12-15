import json
from idlelib.run import manage_socket
from typing import TypedDict, List, Dict, Optional, Tuple
import random


class ChengyuManager:
    def __init__(self, json_file_path: str):
        """
        初始化成语管理器
        :param json_file_path: 成语JSON文件路径
        """
        self.json_file_path = json_file_path
        self.chengyu_dict: Dict[str, Dict] = {}  # 成语到完整信息的映射
        self.pinyin_dict: Dict[str, Dict] = {}  # 拼音到成语的映射（如果需要）

        self._load_chengyu_data()

    def _load_chengyu_data(self):
        """加载成语数据并构建索引"""
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                chengyu_list = json.load(f)  # 假设是列表格式

            # 构建成语到完整信息的映射
            for item in chengyu_list:
                word = item["word"]
                self.chengyu_dict[word] = item

                # 可选：构建拼音索引
                pinyin_key = item["pinyin_r"].replace(" ", "")  # 移除空格
                self.pinyin_dict[pinyin_key] = item

            print(f"✅ 加载成语 {len(self.chengyu_dict)} 条")

        except FileNotFoundError:
            print(f"❌ 文件不存在: {self.json_file_path}")
        except json.JSONDecodeError:
            print(f"❌ JSON解析错误: {self.json_file_path}")

    def get_chengyu_info(self, user_input: str) -> Optional[Dict]:
        """
        获取成语的完整信息（包括拼音）
        :param user_input: 用户输入的成语（如"阿鼻地狱"）
        :return: 成语信息字典或None
        """
        # 方法1：直接字典查找（O(1)时间复杂度）
        if user_input in self.chengyu_dict:
            return self.chengyu_dict[user_input]

        # 方法2：如果用户输入可能有空格或特殊字符，可以清理后查找
        cleaned = user_input.strip()
        if cleaned in self.chengyu_dict:
            return self.chengyu_dict[cleaned]

        # 方法3：尝试模糊匹配（如果考虑繁简体）
        # 可以在这里添加繁简体转换

        return None

    def get_first_last_pinyin(self, user_input: str) -> Optional[Tuple[str, str]]:
        """
        获取成语的首字拼音和末字拼音
        :param user_input: 用户输入的成语
        :return: (首字拼音, 末字拼音) 或 None
        """
        info = self.get_chengyu_info(user_input)
        if info:
            # 从JSON中直接获取已经处理好的拼音
            first_pinyin = info["first"]  # "a"
            last_pinyin = info["last"]  # "yu"
            return first_pinyin, last_pinyin
        return None

    def get_random_chengyu(self) -> Optional[str]:
        return random.choice(list(self.chengyu_dict.keys()))

manager = ChengyuManager('../../data/idiom.json')

print(manager.get_chengyu_info("阿鼻地狱"))
print(manager.get_first_last_pinyin("阿鼻地狱"))
print(manager.get_random_chengyu())