import sqlite3
conn = sqlite3.connect('/home/user/Silver-Labs/Silver-Pool/data/pool.sqlite3')
# Check shares table schema
schema = conn.execute("PRAGMA table_info(shares)").fetchall()
print('shares schema:')
for col in schema:
    print(f'  {col}')
# Check rounds table
try:
    schema2 = conn.execute("PRAGMA table_info(rounds)").fetchall()
    print('rounds schema:')
    for col in schema2:
        print(f'  {col}')
except:
    print('no rounds table')
conn.close()