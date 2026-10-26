import sqlite3
conn = sqlite3.connect('/home/user/Silver-Labs/Silver-Pool/data/pool.sqlite3')
# Add round_id column to shares table
try:
    conn.execute("ALTER TABLE shares ADD COLUMN round_id TEXT")
    print('Added round_id column to shares table')
except sqlite3.OperationalError as e:
    print(f'Could not add column: {e}')
conn.commit()
# Verify
schema = conn.execute("PRAGMA table_info(shares)").fetchall()
print('Updated shares schema:')
for col in schema:
    print(f'  {col}')
conn.close()