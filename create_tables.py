import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# 连接数据库并执行建表语句
try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # 读取 schema.sql 文件
    with open("schema.sql", "r", encoding="utf-8") as f:
        sql_script = f.read()

    # 执行建表
    cur.execute(sql.SQL(sql_script))
    conn.commit()
    
    print("✅ 数据表创建成功！")

except Exception as e:
    print(f"❌ 错误：{e}")

finally:
    if conn:
        cur.close()
        conn.close()