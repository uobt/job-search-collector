import sqlite3

conn = sqlite3.connect("data/collector.db")
cur = conn.execute(
    "update jobs set posted_raw=null where posted_raw='nan'")
cur2 = conn.execute(
    "update jobs set description=null where description='nan'")
conn.commit()
print("posted_raw cleaned:", cur.rowcount, "| description cleaned:", cur2.rowcount)
conn.close()
