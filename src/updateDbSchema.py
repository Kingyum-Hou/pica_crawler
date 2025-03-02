import sqlite3

def update_db_schema(db_path='./downloaded.db'):
    """
    更新数据库模式，向已存在的表格添加新的字段。
    """
    conn = sqlite3.connect(db_path)  # 连接到 SQLite 数据库
    cursor = conn.cursor()  # 获取一个游标对象
    
    # 添加新的字段 'leaderboard_count' 和 'tags'
    """
    cursor.execute('''
    ALTER TABLE downloaded_comics
    ADD COLUMN leaderboard_count INTEGER;
    ''')
    """
    cursor.execute('''
    ALTER TABLE downloaded_comics
    ADD COLUMN tags TEXT;
    ''')
    
    # 提交更改并关闭连接
    conn.commit()
    conn.close()

# 示例使用
update_db_schema('./downloaded.db')
