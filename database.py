import sqlite3
import datetime

ADMIN_ID = '7427250253'  # ID главного администратора

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
                last_request_time DATETIME,
                roles TEXT)''')  # Добавлен столбец roles
    
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

    # Создание таблицы admin_access для хранения информации о доступе администраторов
    c.execute('''CREATE TABLE IF NOT EXISTS admin_access (
                user_id INTEGER PRIMARY KEY,
                FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
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

def is_admin(user_id):
    admin = fetch_one("SELECT * FROM admin_access WHERE user_id = ?", (user_id,))
    return admin is not None

def add_admin(user_id):
    execute_query("INSERT OR IGNORE INTO admin_access (user_id) VALUES (?)", (user_id,))

def remove_admin(user_id):
    execute_query("DELETE FROM admin_access WHERE user_id = ?", (user_id,))

def can_access_admin_panel(user_id):
    # Добавляем отладочный вывод
    print(f"Проверка доступа для user_id: {user_id}")
    print(f"ADMIN_ID: {ADMIN_ID}")
    if str(user_id) == ADMIN_ID:
        print("Пользователь является главным администратором.")
        return True
    if is_admin(user_id):
        print("Пользователь является администратором.")
        return True
    print("Пользователь не имеет доступа к админ панели.")
    return False

def can_access_admin_list(user_id):
    return str(user_id) == ADMIN_ID

# Тестирование
def test_access():
    # Добавим главного администратора в базу данных пользователей
    execute_query("INSERT OR IGNORE INTO users (user_id, username, status, roles) VALUES (?, ?, ?, ?)",
                  (ADMIN_ID, 'main_admin', 'active', 'admin'))

    # Проверка доступа к админ панели для главного администратора
    user_id = ADMIN_ID
    if can_access_admin_panel(user_id):
        print("Доступ к админ панели разрешен.")
    else:
        print("У вас нет доступа к админ панели.")

# Инициализация базы данных и тестирование
init_db()
test_access()
