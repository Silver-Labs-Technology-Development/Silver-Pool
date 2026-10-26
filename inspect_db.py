import sqlite3
conn = sqlite3.connect('/home/user/Silver-Labs/Silver-Pool/data/pool.sqlite3')
tables = conn.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()
print("Tables:", tables)
for table in tables:
    tname = table[0]
    count = conn.execute(f'SELECT COUNT(*) FROM {tname}').fetchone()[0]
    print(f"  {tname}: {count} rows")
conn.close()