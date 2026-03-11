import sqlite3

conn = None
cursor = None


def init_db():
    global conn, cursor
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                      (
                          tg_id
                              INTEGER
                              PRIMARY
                                  KEY,
                          is_approved
                              INTEGER
                      )''')
    conn.commit()


def close_db():
    global conn
    if conn:
        conn.close()
        print("Database disconnected.")
    else:
        print("Database was not connected.")


def is_user_approved(tg_id):
    if not cursor or not conn:
        return None
    cursor.execute('SELECT is_approved FROM users WHERE tg_id = ?', (tg_id,))
    res = cursor.fetchone()
    return res[0] if res else None


def add_user(tg_id, is_approved=0):
    if not cursor or not conn:
        return None
    cursor.execute('INSERT OR IGNORE INTO users (tg_id, is_approved) VALUES (?, ?)', (tg_id, is_approved))
    cursor.execute('UPDATE users SET is_approved = ? WHERE tg_id = ?', (is_approved, tg_id))
    return conn.commit()
