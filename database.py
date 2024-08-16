import sqlite3
import datetime

ADMIN_ID = '1083294848'

def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    c.execute('''DROP TABLE IF EXISTS numbers''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                status TEXT,
                last_request_time DATETIME,
                roles TEXT,
                earnings REAL DEFAULT 0)''') 
    
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                status TEXT,
                request_time DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS numbers (
                number_id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT,
                service TEXT,
                user_id INTEGER,
                issued_to INTEGER,
                issued_time DATETIME,
                success INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                add_date DATE,
                add_time TIME,
                FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS stats (
                date DATE PRIMARY KEY,
                whatsapp_success INTEGER,
                whatsapp_total INTEGER,
                telegram_success INTEGER,
                telegram_total INTEGER)''')

    c.execute('''CREATE TABLE IF NOT EXISTS counter (
                id INTEGER PRIMARY KEY,
                count INTEGER)''')

    c.execute('''CREATE TABLE IF NOT EXISTS blackjack_game (
                user_id INTEGER PRIMARY KEY,
                player_hand TEXT,
                dealer_hand TEXT,
                bet REAL,
                FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS roulette_game (
                user_id INTEGER PRIMARY KEY,
                bet REAL,
                color TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id))''')

    c.execute("INSERT OR IGNORE INTO counter (id, count) VALUES (1, 0)")
    
    c.execute("INSERT OR IGNORE INTO users (user_id, username, status, roles) VALUES (?, ?, ?, ?)",
              (ADMIN_ID, 'main_admin', 'approved', 'admin'))

    c.execute('''CREATE TABLE IF NOT EXISTS prices (
                service TEXT PRIMARY KEY,
                price REAL)''')
    
    c.execute("INSERT OR IGNORE INTO prices (service, price) VALUES ('whatsapp', 3.2), ('telegram', 1.8)")
    
    conn.commit()
    conn.close()

# Остальные функции (execute_query, fetch_all, fetch_one, reset_counter и т.д.) остаются без изменений

def execute_query(query, params=()):
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        print(f"Executed query: {query} with params: {params}")  # Debugging information
        conn.close()
    except sqlite3.Error as e:
        print(f"Database error: {e}")  # Debugging information

def delete_number_entry(number, add_date, add_time):
    print(f"Deleting number {number} with add_date {add_date} and add_time {add_time}")
    db.execute_query("DELETE FROM numbers WHERE number = ? AND add_date = ? AND add_time = ?", (number, add_date, add_time))
    # Verify if the number is deleted
    result = db.fetch_one("SELECT * FROM numbers WHERE number = ? AND add_date = ? AND add_time = ?", (number, add_date, add_time))
    if result:
        print(f"Number {number} still exists in the database: {result}")
    else:
        print(f"Number {number} successfully deleted from the database.")

def fetch_all(query, params=()):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def fetch_one(query, params=()):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute(query, params)
    row = c.fetchone()
    conn.close()
    return row

def reset_counter():
    execute_query("UPDATE counter SET count = 0 WHERE id = 1")

def increment_counter():
    execute_query("UPDATE counter SET count = count + 1 WHERE id = 1")

def decrement_counter():
    execute_query("UPDATE counter SET count = count - 1 WHERE id = 1")

def get_counter():
    row = fetch_one("SELECT count FROM counter WHERE id = 1")
    return row[0] if row else 0

def get_price(service):
    row = fetch_one("SELECT price FROM prices WHERE service = ?", (service,))
    return row[0] if row else None

def update_price(service, new_price):
    execute_query("UPDATE prices SET price = ? WHERE service = ?", (new_price, service))

def update_stats(service, success):
    date = datetime.date.today()
    stats = fetch_one("SELECT * FROM stats WHERE date = ?", (date,))
    if stats:
        if service == 'whatsapp':
            if success:
                execute_query("UPDATE stats SET whatsapp_success = whatsapp_success + 1 WHERE date = ?", (date,))
            execute_query("UPDATE stats SET whatsapp_total = whatsapp_total + 1 WHERE date = ?", (date,))
        elif service == 'telegram':
            if success:
                execute_query("UPDATE stats SET telegram_success = telegram_success + 1 WHERE date = ?", (date,))
            execute_query("UPDATE stats SET telegram_total = telegram_total + 1 WHERE date = ?", (date,))
    else:
        if service == 'whatsapp':
            execute_query("INSERT INTO stats (date, whatsapp_success, whatsapp_total, telegram_success, telegram_total) VALUES (?, ?, ?, ?, ?)",
                          (date, 1 if success else 0, 1, 0, 0))
        elif service == 'telegram':
            execute_query("INSERT INTO stats (date, whatsapp_success, whatsapp_total, telegram_success, telegram_total) VALUES (?, ?, ?, ?, ?)",
                          (date, 0, 0, 1 if success else 0, 1))

def get_stats():
    date = datetime.date.today()
    stats = fetch_one("SELECT * FROM stats WHERE date = ?", (date,))
    return stats if stats else (date, 0, 0, 0, 0)

def remove_numbers_by_user(user_id):
    execute_query("DELETE FROM numbers WHERE issued_to = ?", (user_id,))

def mark_successful(number):
    # Получаем информацию о сервисе и пользователе, которому выдан номер
    service_info = fetch_one("SELECT service, issued_to, success FROM numbers WHERE number = ?", (number,))
    if service_info:
        service, issued_to, success_status = service_info
        # Проверяем, был ли номер уже помечен как успешный
        if success_status == 0: 
            earnings = get_price(service)
            execute_query("UPDATE numbers SET success = 1 WHERE number = ?", (number,))
            execute_query("UPDATE users SET earnings = earnings + ? WHERE user_id = ?", (earnings, issued_to))
            update_stats(service, success=True)

def is_admin(user_id):
    user = fetch_one("SELECT roles FROM users WHERE user_id = ?", (user_id,))
    return user and 'admin' in user[0].split(',')

def can_access_admin_panel(user_id):
    if str(user_id) == ADMIN_ID:
        return True
    return is_admin(user_id)

def can_access_admin_list(user_id):
    return str(user_id) == ADMIN_ID

def can_access_worker_list(user_id):
    roles = fetch_one("SELECT roles FROM users WHERE user_id = ?", (user_id,))
    if roles and 'admin' in roles[0].split(','):
        return True
    return False

def store_daily_stats():
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    stats = fetch_one("SELECT * FROM stats WHERE date = ?", (yesterday,))
    if stats:
        execute_query("INSERT OR IGNORE INTO weekly_stats (date, whatsapp_success, whatsapp_total, telegram_success, telegram_total) VALUES (?, ?, ?, ?, ?)",
                      (stats[0], stats[1], stats[2], stats[3], stats[4]))
        execute_query("DELETE FROM weekly_stats WHERE date < ?", (today - datetime.timedelta(days=7),))

def update_earnings(user_id, amount):
    execute_query("UPDATE users SET earnings = earnings + ? WHERE user_id = ?", (amount, user_id))

def fetch_user_earnings(user_id):
    row = fetch_one("SELECT earnings FROM users WHERE user_id = ?", (user_id,))
    return row[0] if row else 0

def init_weekly_stats():
    execute_query('''CREATE TABLE IF NOT EXISTS weekly_stats (
                        date DATE PRIMARY KEY,
                        whatsapp_success INTEGER,
                        whatsapp_total INTEGER,
                        telegram_success INTEGER,
                        telegram_total INTEGER)''')

def test_access():
    execute_query("INSERT OR IGNORE INTO users (user_id, username, status, roles) VALUES (?, ?, ?, ?)",
                  (ADMIN_ID, 'main_admin', 'active', 'admin'))

    user_id = ADMIN_ID
    if can_access_admin_panel(user_id):
        print("Доступ к админ панели разрешен.")
    else:
        print("У вас нет доступа к админ панели.")

init_db()
init_weekly_stats()
test_access()
