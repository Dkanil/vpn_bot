import sqlite3
import time

conn = None
cursor = None


def init_db():
    global conn, cursor
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                      (
                          tg_id       INTEGER PRIMARY KEY,
                          is_approved INTEGER
                      )''')

    columns_to_add = {
        'creation_date': 'INTEGER',
        'paid_until': 'INTEGER',
        'group_name': 'TEXT',
        'notify_level': 'INTEGER DEFAULT 0',
        'email': 'TEXT',
        'username': 'TEXT'
    }
    for col, col_type in columns_to_add.items():
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
        except sqlite3.OperationalError:
            pass
    conn.commit()


def close_db():
    global conn
    if conn:
        conn.close()
        print("Database disconnected.")
    else:
        print("Database was not connected.")


def update_username(tg_id, username):
    if not cursor or not conn:
        return
    cursor.execute('UPDATE users SET username = ? WHERE tg_id = ?', (username, tg_id))
    conn.commit()


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


def get_vpn_users():
    if not cursor or not conn:
        return []
    cursor.execute('SELECT tg_id FROM users WHERE is_approved == 2')
    return [row[0] for row in cursor.fetchall()]


def get_user_email(tg_id):
    cursor.execute('SELECT email FROM users WHERE tg_id = ?', (tg_id,))
    res = cursor.fetchone()
    return res[0] if res else None


def update_user_email(tg_id, email):
    cursor.execute('UPDATE users SET email = ? WHERE tg_id = ?', (email, tg_id))
    conn.commit()


def get_all_vpn_users_full():
    cursor.execute('SELECT tg_id, is_approved, creation_date, paid_until FROM users WHERE is_approved > 0')
    return cursor.fetchall()


def update_user_from_panel(tg_id, creation_date, paid_until, group_name, email=None):
    if email:
        cursor.execute('''UPDATE users
                          SET creation_date = COALESCE(creation_date, ?),
                              paid_until    = COALESCE(paid_until, ?),
                              group_name    = ?,
                              email         = COALESCE(email, ?)
                          WHERE tg_id = ?''',
                       (creation_date, paid_until, group_name, email, tg_id))
    else:
        cursor.execute('''UPDATE users
                          SET creation_date = COALESCE(creation_date, ?),
                              paid_until    = COALESCE(paid_until, ?),
                              group_name    = ?
                          WHERE tg_id = ?''',
                       (creation_date, paid_until, group_name, tg_id))
    conn.commit()


def extend_payment(tg_id, months=3):
    cursor.execute('SELECT paid_until FROM users WHERE tg_id = ?', (tg_id,))
    res = cursor.fetchone()
    if not res:
        return False

    now = int(time.time())
    base_date = res[0] if res[0] else now
    new_paid_until = base_date + (months * 30 * 24 * 3600)

    cursor.execute('UPDATE users SET paid_until = ?, notify_level = 0 WHERE tg_id = ?', (new_paid_until, tg_id))
    conn.commit()
    return True


def set_notify_level(tg_id, level):
    cursor.execute('UPDATE users SET notify_level = ? WHERE tg_id = ?', (level, tg_id))
    conn.commit()


def get_users_for_payment_check():
    cursor.execute('''SELECT tg_id, paid_until, notify_level
                      FROM users
                      WHERE is_approved = 2
                        AND (group_name IS NULL OR group_name != 'private')''')
    return cursor.fetchall()


def get_users_by_payment_status():
    cursor.execute('''SELECT tg_id, paid_until, username
                      FROM users
                      WHERE is_approved = 2
                        AND (group_name IS NULL OR group_name != 'private')''')
    rows = cursor.fetchall()
    status_1, status_0, status_minus_1 = [], [], []
    now = int(time.time())

    for tg_id, paid_until, username in rows:
        user_info = (tg_id, username)
        if not paid_until:
            status_1.append(user_info)
            continue

        left_seconds = paid_until - now
        if left_seconds > 7 * 24 * 3600:
            status_1.append(user_info)
        elif left_seconds > 0:
            status_0.append(user_info)
        else:
            status_minus_1.append(user_info)

    return status_1, status_0, status_minus_1
