import csv
import sqlite3
import os

# 配置文件名
CSV_FILE = 'ecdict.csv'
DB_FILE = 'word_game.db'


def safe_int(value, default=0):
    """安全地将字符串转换为整数，如果为空或非法则返回默认值"""
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def create_database():
    # 如果文件已存在，先删除（可选，为了每次运行都是新的）
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 创建表结构
    print("正在创建数据库表结构...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS dictionary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT NOT NULL UNIQUE,
        phonetic TEXT,
        definition TEXT,
        translation TEXT,
        pos TEXT,
        collins INTEGER DEFAULT 0,
        oxford INTEGER DEFAULT 0,
        tag TEXT,
        bnc INTEGER DEFAULT 99999999,
        frq INTEGER DEFAULT 99999999,
        exchange TEXT
    );
    ''')

    # 创建索引以加速游戏时的随机抽取速度
    cursor.execute('CREATE INDEX idx_collins ON dictionary(collins);')
    cursor.execute('CREATE INDEX idx_tag ON dictionary(tag);')
    cursor.execute('CREATE INDEX idx_word ON dictionary(word);')

    conn.commit()
    return conn


def import_csv_to_db(conn):
    cursor = conn.cursor()
    print(f"正在读取 {CSV_FILE} 并导入数据，这可能需要几秒钟...")

    # 这里的 encoding='utf-8' 非常重要
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        # 使用 DictReader 自动处理标题行
        reader = csv.DictReader(f)

        batch_data = []
        count = 0

        for row in reader:
            # 数据清洗与准备
            data = (
                row.get('word'),
                row.get('phonetic'),
                row.get('definition'),
                row.get('translation'),
                row.get('pos'),
                safe_int(row.get('collins'), 0),  # 转换为整数
                safe_int(row.get('oxford'), 0),  # 转换为整数
                row.get('tag'),
                safe_int(row.get('bnc'), 0),
                safe_int(row.get('frq'), 0),
                row.get('exchange')
            )
            batch_data.append(data)

            # 每 5000 条提交一次，提高速度
            if len(batch_data) >= 5000:
                cursor.executemany('''
                    INSERT OR IGNORE INTO dictionary 
                    (word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch_data)
                conn.commit()
                batch_data = []
                count += 5000
                print(f"已处理 {count} 条词条...")

        # 处理剩余的数据
        if batch_data:
            cursor.executemany('''
                INSERT OR IGNORE INTO dictionary 
                (word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', batch_data)
            conn.commit()

    print("导入完成！")


if __name__ == '__main__':
    try:
        conn = create_database()
        import_csv_to_db(conn)
        conn.close()
        print(f"数据库制作成功：{DB_FILE}")
    except FileNotFoundError:
        print(f"错误：找不到文件 {CSV_FILE}，请确保它和脚本在同一目录下。")
    except Exception as e:
        print(f"发生错误：{e}")