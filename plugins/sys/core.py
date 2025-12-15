"""
SoraBot 内核
- 创建 SQLite 单文件 & 表
- 提供 DAO 单例
"""
import os
from datetime import datetime
from pydantic import BaseModel
import json, time, aiosqlite
from typing import Any, List, Tuple, Optional

# 确保目录存在
DB_DIR = os.path.join('config', 'db')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'sorabot.db')

# 在 core.py 的 DB_PATH 定义后添加

# WordGame 数据库路径
DB_DIR_WORDGAME = os.path.join('config', 'db')
WORDGAME_DB_PATH = os.path.join(DB_DIR, 'word_game.db')


class WordGameDAO:
    """单词游戏数据库访问对象"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def get_random_word(self, difficulty: str) -> Optional[dict]:
        """
        根据难度获取随机单词
        difficulty: easy/normal/hard/hell
        """
        # 难度映射到SQL查询条件
        difficulty_map = {
            "easy": "collins >= 3 AND (tag LIKE '%gk%')",
            "normal": "collins >= 2 AND (tag LIKE '%cet4%' OR tag LIKE '%cet6%' OR tag LIKE '%ky%')",
            "hard": "collins >= 1 AND (tag LIKE '%tem4%' OR tag LIKE '%ielts%' OR tag LIKE '%toefl%')",
            "hell": "(tag LIKE '%tem8%' OR tag LIKE '%gre%' OR tag LIKE '%sat%')"
        }

        where_clause = difficulty_map.get(difficulty, "collins >= 2")

        async with aiosqlite.connect(WORDGAME_DB_PATH) as conn:
            cursor = await conn.execute(
                f"SELECT * FROM dictionary WHERE {where_clause} ORDER BY RANDOM() LIMIT 1"
            )
            row = await cursor.fetchone()

            if row:
                columns = ['id', 'word', 'phonetic', 'definition', 'translation',
                           'pos', 'collins', 'oxford', 'tag', 'bnc', 'frq', 'exchange']
                return dict(zip(columns, row))
            return None

    async def get_word_by_exact_match(self, word: str) -> Optional[dict]:
        """精确匹配单词"""
        async with aiosqlite.connect(WORDGAME_DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT * FROM dictionary WHERE word = ? LIMIT 1",
                (word,)
            )
            row = await cursor.fetchone()

            if row:
                columns = ['id', 'word', 'phonetic', 'definition', 'translation',
                           'pos', 'collins', 'oxford', 'tag', 'bnc', 'frq', 'exchange']
                return dict(zip(columns, row))
            return None

    async def get_word_by_fuzzy_match(self, word: str) -> Optional[dict]:
        """模糊匹配（使用exchange字段）"""
        async with aiosqlite.connect(WORDGAME_DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT * FROM dictionary WHERE exchange LIKE ? LIMIT 1",
                (f"%{word}%",)
            )
            row = await cursor.fetchone()

            if row:
                columns = ['id', 'word', 'phonetic', 'definition', 'translation',
                           'pos', 'collins', 'oxford', 'tag', 'bnc', 'frq', 'exchange']
                return dict(zip(columns, row))
            return None





# ---------- 数据模型 ----------
class User(BaseModel):
    qq: str
    nick: str = ''
    exp: int = 0
    coin: int = 0
    created_at: datetime = datetime.now()


# ---------- DAO ----------
class CoreDAO:
    """单例 DAO：用户/群组 基础 CURD"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # 异步初始化表（只跑一次）
            import asyncio
            asyncio.create_task(cls._instance._init_schema())
        return cls._instance

    async def _init_schema(self):
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    qq         TEXT PRIMARY KEY,
                    nick       TEXT,
                    exp        INTEGER DEFAULT 0,
                    coin       INTEGER DEFAULT 0,
                    created_at TEXT
                );
            ''')

            # 在 CoreDAO._init_schema() 中添加：
            # ✅ 修复：先创建群聊消息表（不含 INDEX 定义）
            await conn.execute('''
                        CREATE TABLE IF NOT EXISTS group_messages (
                            id         INTEGER PRIMARY KEY AUTOINCREMENT,
                            group_id   TEXT NOT NULL,
                            user_id    TEXT NOT NULL,
                            nickname   TEXT,
                            message    TEXT NOT NULL,
                            timestamp  REAL NOT NULL
                        );
                    ''')

            # ✅ 修复：单独创建索引
            await conn.execute('''
                        CREATE INDEX IF NOT EXISTS idx_group_time 
                        ON group_messages(group_id, timestamp);
                    ''')

            # 新增 kv 表（只跑一次）
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS kv(
                    store_key   TEXT PRIMARY KEY,
                    store_value TEXT
                );
            ''')
            await conn.commit()

    # 查用户（None 表示未注册）
    async def get_user(self, qq: str) -> User | None:
        async with aiosqlite.connect(DB_PATH) as conn:
            cur = await conn.execute('SELECT * FROM users WHERE qq=?', (qq,))
            row = await cur.fetchone()
            if not row:
                return None
            return User(
                qq=row[0],
                nick=row[1] or '',
                exp=row[2],
                coin=row[3],
                created_at=datetime.fromisoformat(row[4])
            )

    # ===== 通用 KV =====
    async def set_key(self, key: str, value: str) -> None:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('INSERT OR REPLACE INTO kv(store_key, store_value) VALUES(?,?)', (key, value))
            await conn.commit()

    async def get_key(self, key: str) -> str | None:
        async with aiosqlite.connect(DB_PATH) as conn:
            cur = await conn.execute('SELECT store_value FROM kv WHERE store_key=?', (key,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def del_key(self, key: str) -> None:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('DELETE FROM kv WHERE store_key=?', (key,))
            await conn.commit()

    # ===== TTL 版 =====
    async def set_key_ttl(self, key: str, value: Any, ttl_seconds: int) -> None:
        expire_at = int(time.time()) + ttl_seconds
        await self.set_key(key, json.dumps({"v": value, "expire": expire_at}))

    async def get_key_ttl(self, key: str) -> Any | None:
        raw = await self.get_key(key)
        if not raw:
            return None
        data = json.loads(raw)
        if data.get("expire", 0) < int(time.time()):
            await self.del_key(key)          # 惰性删除
            return None
        return data["v"]

    # ===== 批量清理 =====
    async def ttl_cleanup(self) -> int:
        """返回被删除的过期键数量"""
        async with aiosqlite.connect(DB_PATH) as conn:
            cur = await conn.execute('SELECT store_key, store_value FROM kv')
            rows = await cur.fetchall()
            to_del: List[str] = []
            for k, v in rows:
                try:
                    if json.loads(v).get("expire", 0) < int(time.time()):
                        to_del.append(k)
                except Exception:
                    continue
            if to_del:
                placeholders = ",".join("?" * len(to_del))
                await conn.execute(f'DELETE FROM kv WHERE store_key IN ({placeholders})', to_del)
                await conn.commit()
            return len(to_del)


    # 增加经验/金币（自动 INSERT OR IGNORE）
    async def add_exp_coin(self, qq: str, exp: int = 0, coin: int = 0):
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                'INSERT OR IGNORE INTO users(qq, created_at) VALUES(?, ?)',
                (qq, datetime.now().isoformat())
            )
            await conn.execute(
                'UPDATE users SET exp = exp + ?, coin = coin + ? WHERE qq = ?',
                (exp, coin, qq)
            )
            await conn.commit()

    # 存储群聊消息
    async def store_group_message(self, group_id: str, user_id: str,
                                  nickname: str, message: str):
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                'INSERT INTO group_messages (group_id, user_id, nickname, message, timestamp) '
                'VALUES (?, ?, ?, ?, ?)',
                (group_id, user_id, nickname, message, time.time())
            )
            await conn.commit()

    # 按时间范围获取消息
    async def get_messages_by_time_range(self, group_id: str,
                                         hours: float) -> List[dict]:
        """获取过去N小时的消息"""
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                'SELECT user_id, nickname, message, timestamp '
                'FROM group_messages '
                'WHERE group_id = ? AND timestamp > ? '
                'ORDER BY timestamp ASC',
                (group_id, time.time() - hours * 3600)
            )
            rows = await cursor.fetchall()

            return [{
                "user_id": row[0],
                "nickname": row[1],
                "message": row[2],
                "timestamp": row[3]
            } for row in rows]

    # 清理过期消息（如7天前）
    async def cleanup_old_messages(self, group_id: str, max_age_days: int = 7):
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                'DELETE FROM group_messages '
                'WHERE group_id = ? AND timestamp < ?',
                (group_id, time.time() - max_age_days * 86400)
            )
            await conn.commit()




# ---------- 单例 ----------
dao = CoreDAO()

# 创建WordGameDAO单例
wordgame_dao = WordGameDAO()