import sqlite3
import datetime

def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Удаление старой таблицы numbers
    c.execute('''DROP TABLE IF EXISTS numbers''')
    
    # Создание таблицы users
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                status TEXT,
                last_request_time DATETIME)''')
    
    # Создание таблицы requests
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                status TEXT,
                request_time DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # Создание таблицы numbers
    c.execute('''CREATE TABLE IF NOT EXISTS numbers (
                number_id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT,
                service TEXT,
                user_id INTEGER,
                issued_to INTEGER,
                issued_time DATETIME,
                success INTEGER DEFAULT 0,
                add_date DATE,
                add_time TIME,
                FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # Создание таблицы stats для статистики
    c.execute('''CREATE TABLE IF NOT EXISTS stats (
                date DATE PRIMARY KEY,
                whatsapp_success INTEGER,
                whatsapp_total INTEGER,
                telegram_success INTEGER,
                telegram_total INTEGER)''')

    # Создание таблицы counter для счетчика успешно выданных номеров
    c.execute('''CREATE TABLE IF NOT EXISTS counter (
                id INTEGER PRIMARY KEY,
                count INTEGER)''')
    
    # Инициализация счетчика
    c.execute("INSERT OR IGNORE INTO counter (id, count) VALUES (1, 0)")
    
    conn.commit()
    conn.close()

def execute_query(query, params=()):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

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

def mark_successful(number):
    execute_query("UPDATE numbers SET success = 1 WHERE number = ?", (number,))
    number_info = fetch_one("SELECT service FROM numbers WHERE number = ?", (number,))
    if number_info:
        service = number_info[0]
        update_stats(service, success=True)
