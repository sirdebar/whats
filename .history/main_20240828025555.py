import telebot
from telebot import types
import datetime
import time
import threading
from threading import Thread, Timer
import random
import config
import signal
import requests
from requests.exceptions import ReadTimeout, ConnectionError
import random
import database as db 

bot = telebot.TeleBot(config.API_TOKEN, parse_mode='HTML')

active_timers = {}
user_data = {}
admin_data = {}
recently_issued_numbers = {
    'whatsapp': [],
    'telegram': []
}
sms_requests = {}
request_tracker = {}
request_ids = {}  # Хранение информации о запросах
request_counter = 0  # Счетчик для уникальных ID запросов

def get_group_id(message):
    return message.chat.id

# Декоратор для проверки активности группы перед выполнением команд
def group_required(func):
    def wrapper(message, *args, **kwargs):
        group_id = get_group_id(message)
        if db.is_group_active(group_id):
            return func(message, *args, **kwargs)
        else:
            bot.send_message(group_id, "Бот не активен в этой группе. Попросите администратора активировать его с помощью команды /gadd.")
    return wrapper

# Добавление группы в активные
@bot.message_handler(commands=['gadd'])
def add_group_command(message):
    group_id = get_group_id(message)
    if db.is_admin(message.from_user.id):  # Проверяем права пользователя
        db.add_group(group_id)
        bot.send_message(group_id, "Группа добавлена в список активных.")
    else:
        bot.send_message(group_id, "У вас нет прав для выполнения этой команды.")

# Удаление группы из активных
@bot.message_handler(commands=['gdel'])
def delete_group_command(message):
    group_id = get_group_id(message)
    if db.is_admin(message.from_user.id):  # Проверяем права пользователя
        db.remove_group(group_id)
        bot.send_message(group_id, "Группа удалена из списка активных.")
    else:
        bot.send_message(group_id, "У вас нет прав для выполнения этой команды.")

@bot.message_handler(func=lambda message: message.text == '💰 Изменить цену')
def change_price(message):
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton('WhatsApp', callback_data='change_price_whatsapp')
    btn2 = types.InlineKeyboardButton('Telegram', callback_data='change_price_telegram')
    markup.add(btn1, btn2)
    bot.send_message(message.chat.id, "Выберите:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('change_price_'))
def select_service_to_change_price(call):
    service = call.data.split('_')[-1]
    current_price = db.get_price(service)
    msg = bot.send_message(call.message.chat.id, f"Актуальная цена {current_price}$ за {service.capitalize()}. Введите новую цену:")
    bot.register_next_step_handler(msg, process_new_price, service)

def process_new_price(message, service):
    try:
        new_price = float(message.text)
        db.update_price(service, new_price)
        bot.send_message(message.chat.id, f"Цена за {service.capitalize()} успешно обновлена на {new_price}$")
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректное число.")
        change_price(message)

def retry_request(func, *args, retries=3, delay=2, **kwargs):
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except (ReadTimeout, ConnectionError):
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise

def init_user_data(user_id, username):
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not user:
        db.execute_query("INSERT INTO users (user_id, username, status, last_request_time, roles) VALUES (?, ?, ?, ?, ?)",
                         (user_id, username, 'pending', None, ''))
    else:
        roles = user[4].split(',')
        if str(user_id) == config.ADMIN_ID and 'admin' not in roles:
            add_role(user_id, 'admin')

def add_role(user_id, role):
    user = db.fetch_one("SELECT roles FROM users WHERE user_id = ?", (user_id,))
    if user:
        roles = user[0]
        if role not in roles.split(','):
            roles = roles + f",{role}" if roles else role
            db.execute_query("UPDATE users SET roles = ? WHERE user_id = ?", (roles, user_id))

def remove_role(user_id, role):
    user = db.fetch_one("SELECT roles FROM users WHERE user_id = ?", (user_id,))
    if user:
        roles = user[0].split(',')
        if role in roles:
            roles.remove(role)
            db.execute_query("UPDATE users SET roles = ? WHERE user_id = ?", (','.join(roles), user_id))
            if role == 'worker':
                show_pending_menu_by_user_id(user_id)

def show_pending_menu_by_user_id(user_id):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    btn1 = types.KeyboardButton('Отправить заявку на вступление')
    markup.add(btn1)
    bot.send_message(user_id, "🔓 <b>У вас нет доступа к функционалу. Пожалуйста, отправьте заявку на вступление.</b>", reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username

    if str(user_id) == config.ADMIN_ID:
        add_role(user_id, 'admin')
        show_admin_main_menu(message)
        return

    init_user_data(user_id, username)
    user = db.fetch_one("SELECT status, roles FROM users WHERE user_id = ?", (user_id,))
    if user[0] == 'approved' or 'admin' in user[1].split(',') or 'worker' in user[1].split(','):
        user_data[user_id] = {'whatsapp': [], 'telegram': [], 'start_time': None, 'sms_requests': {}}
        markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
        btn1 = types.KeyboardButton('🔄 Начать работу')
        markup.add(btn1)
        bot.send_message(message.chat.id, "Добро пожаловать!\n\n🔄 Нажмите 'Начать работу' для начала.", reply_markup=markup)
    else:
        show_pending_menu(message)

def show_pending_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    btn1 = types.KeyboardButton('Отправить заявку на вступление')
    btn2 = types.KeyboardButton('Мои заявки')
    markup.add(btn1, btn2)
    bot.send_message(message.chat.id, "Вы не имеете доступа к функционалу. Пожалуйста, отправьте заявку на вступление.", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == 'Отправить заявку на вступление')
def request_access(message):
    user_id = message.from_user.id
    username = message.from_user.username
    now = datetime.datetime.now()

    user = db.fetch_one("SELECT last_request_time FROM users WHERE user_id = ?", (user_id,))
    
    if user and user[0]:
        try:
            last_request_time = datetime.datetime.strptime(user[0], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            last_request_time = datetime.datetime.strptime(user[0], '%Y-%m-%d %H:%М:%S')

        if (now - last_request_time).total_seconds() < 10:
            bot.send_message(message.chat.id, "Вы можете подать заявку только через 10 секунд после последней попытки.")
            return

    db.execute_query("INSERT INTO requests (user_id, username, status, request_time) VALUES (?, ?, ?, ?)",
                     (user_id, username, 'pending', now))
    db.execute_query("UPDATE users SET last_request_time = ? WHERE user_id = ?", (now, user_id))
    
    bot.send_message(message.chat.id, "Ваша заявка на вступление отправлена.")
    bot.send_message(config.ADMIN_ID, f"Получена заявка на вступление от @{username}", reply_markup=admin_approval_markup(user_id))

def admin_approval_markup(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("Одобрить", callback_data=f"approve_{user_id}")
    btn2 = types.InlineKeyboardButton("Отказать", callback_data=f"reject_{user_id}")
    markup.add(btn1, btn2)
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_'))
def approve_request(call):
    user_id = int(call.data.split('_')[1])
    db.execute_query("UPDATE users SET status = 'approved' WHERE user_id = ?", (user_id,))
    db.execute_query("UPDATE requests SET status = 'approved' WHERE user_id = ? AND status = 'pending'", (user_id,))
    
    # Добавляем роль worker при одобрении заявки
    add_role(user_id, 'worker')

    bot.send_message(call.message.chat.id, f"Заявка на вступление пользователя с ID {user_id} одобрена.")
    bot.send_message(user_id, "Заявка на вступление одобрена. Добро пожаловать!")
    show_main_menu_by_user_id(user_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_'))
def reject_request(call):
    user_id = int(call.data.split('_')[1])
    db.execute_query("UPDATE requests SET status = 'rejected' WHERE user_id = ? AND status = 'pending'", (user_id,))
    bot.send_message(call.message.chat.id, f"Заявка на вступление пользователя с ID {user_id} отклонена.")
    bot.send_message(user_id, "Вам отказано в доступе. Попробуйте еще раз через 24 часа, если считаете, что это ошибка.")
    bot.answer_callback_query(call.id)

def show_main_menu_by_user_id(user_id):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    btn1 = types.KeyboardButton('➕ Добавить номера')
    btn2 = types.KeyboardButton('📊 Профиль')
    btn3 = types.KeyboardButton('📋 Добавленные номера')
    btn4 = types.KeyboardButton('⏹️ Закончить работу')
    markup.add(btn1, btn2, btn3, btn4)
    bot.send_message(user_id, "🚀 Работа начата!\n\nВыберите действие ниже.", reply_markup=markup)

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    btn1 = types.KeyboardButton('➕ Добавить номера')
    btn2 = types.KeyboardButton('📊 Профиль')
    btn3 = types.KeyboardButton('📋 Добавленные номера')
    btn4 = types.KeyboardButton('⏹️ Закончить работу')
    markup.add(btn1, btn2, btn3, btn4)
    bot.send_message(message.chat.id, "🚀 Работа начата!\n\nВыберите действие ниже.", reply_markup=markup)

def show_admin_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    btn1 = types.KeyboardButton('➕ Добавить номера')
    btn2 = types.KeyboardButton('📊 Профиль')
    btn3 = types.KeyboardButton('📋 Добавленные номера')
    btn4 = types.KeyboardButton('⏹️ Закончить работу')
    btn5 = types.KeyboardButton('🔧 Войти в админ панель')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    bot.send_message(message.chat.id, "🚀 Работа начата!\n\nВыберите действие ниже.", reply_markup=markup)

def show_admin_main_menu_by_user_id(user_id):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    btn1 = types.KeyboardButton('➕ Добавить номера')
    btn2 = types.KeyboardButton('📊 Профиль')
    btn3 = types.KeyboardButton('📋 Добавленные номера')
    btn4 = types.KeyboardButton('⏹️ Закончить работу')
    btn5 = types.KeyboardButton('🔧 Войти в админ панель')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    bot.send_message(user_id, "🚀 Работа начата!\n\nВыберите действие ниже.", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '🔧 Войти в админ панель')
def admin_panel(message):
    user_id = message.from_user.id
    if db.can_access_admin_panel(user_id):
        show_admin_panel(message)
    else:
        bot.send_message(message.chat.id, "У вас нет доступа к админ панели.")

@bot.message_handler(func=lambda message: message.text == '🔙 Выйти из админ панели')
def handle_exit_admin_panel(message):
    user_id = message.from_user.id
    user_roles = db.fetch_one("SELECT roles FROM users WHERE user_id = ?", (user_id,))
    if user_roles and 'admin' in user_roles[0].split(','):
        show_admin_main_menu(message)
    else:
        show_main_menu(message)

def show_admin_panel(message):
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    btn1 = types.KeyboardButton('📊 Статистика')
    btn2 = types.KeyboardButton('👥 Список администраторов')
    btn3 = types.KeyboardButton('👥 Список работников')
    btn4 = types.KeyboardButton('💰 Изменить цену')
    btn5 = types.KeyboardButton('🔄 Обнулить статистику')  # Новая кнопка
    btn6 = types.KeyboardButton('🔙 Выйти из админ панели')
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    bot.send_message(message.chat.id, "🔧 Админ панель", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '🔄 Обнулить статистику')
def reset_stats_handler(message):
    user_id = message.from_user.id
    
    if db.is_admin(user_id):
        reset_worker_stats()  # Обнуляем статистику всех воркеров
        db.reset_counter()  # Обнуляем общий счетчик выданных номеров
        db.execute_query("DELETE FROM numbers")  # Очищаем очередь номеров

        bot.send_message(message.chat.id, "📊 Статистика всех воркеров обнулена, очередь номеров очищена.")
    else:
        bot.send_message(message.chat.id, "🚫 У вас нет прав для выполнения этой команды.")

def reset_worker_stats():
    workers = db.fetch_all("SELECT user_id FROM users WHERE roles LIKE '%worker%'")
    for worker in workers:
        db.execute_query("UPDATE users SET earnings = 0 WHERE user_id = ?", (worker[0],))

@bot.message_handler(func=lambda message: message.text == '📊 Статистика')
def show_stats(message):
    stats = db.get_stats()
    response = f"Статистика на {stats[0]}:\n\n"
    response += f"WhatsApp - Удачных: {stats[1]}, Всего: {stats[2]}\n"
    response += f"Telegram - Удачных: {stats[3]}, Всего: {stats[4]}\n"
    bot.send_message(message.chat.id, response)

@bot.message_handler(func=lambda message: message.text == '👥 Список администраторов')
def list_admins(message):
    if not db.can_access_admin_list(message.from_user.id):
        bot.send_message(message.chat.id, "У вас нет прав на просмотр этого списка.")
        return

    admins = db.fetch_all("SELECT user_id, username FROM users WHERE roles LIKE '%admin%'")
    response = "Список администраторов:\n\n"
    markup = types.InlineKeyboardMarkup()
    for admin in admins:
        response += f"@{admin[1]} (ID: {admin[0]})\n"
        if str(admin[0]) != config.ADMIN_ID:  
            markup.add(types.InlineKeyboardButton(f"Удалить @{admin[1]}", callback_data=f"remove_admin_{admin[0]}"))
    markup.add(types.InlineKeyboardButton('➕ Добавить', callback_data='add_admin'))
    bot.send_message(message.chat.id, response, reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '👥 Список работников')
def list_workers(message):
    if not db.can_access_worker_list(message.from_user.id) and not db.is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "У вас нет прав на просмотр этого списка.")
        return

    workers = db.fetch_all("SELECT user_id, username FROM users WHERE roles LIKE '%worker%'")
    response = "Список работников:\n\n"
    markup = types.InlineKeyboardMarkup()
    for worker in workers:
        response += f"@{worker[1]} (ID: {worker[0]})\n"
        markup.add(types.InlineKeyboardButton(f"Удалить @{worker[1]}", callback_data=f"remove_worker_{worker[0]}"))
    markup.add(types.InlineKeyboardButton('➕ Добавить', callback_data='add_worker'))
    bot.send_message(message.chat.id, response, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'add_worker')
def add_worker(call):
    msg = bot.send_message(call.message.chat.id, "Введите ID пользователя для добавления в работники:")
    bot.register_next_step_handler(msg, process_add_worker)

def process_add_worker(message):
    try:
        user_id = int(message.text)
        add_role(user_id, 'worker')
        bot.send_message(message.chat.id, f"Пользователь с ID {user_id} добавлен в работники.")
        show_main_menu_by_user_id(user_id)
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректный ID пользователя.")

@bot.callback_query_handler(func=lambda call: call.data == 'add_admin')
def add_admin(call):
    msg = bot.send_message(call.message.chat.id, "Введите ID пользователя для добавления в администраторы:")
    bot.register_next_step_handler(msg, process_add_admin)

def process_add_admin(message):
    try:
        user_id = int(message.text)
        add_role(user_id, 'admin')
        bot.send_message(message.chat.id, f"Пользователь с ID {user_id} добавлен в администраторы.")
        show_admin_main_menu_by_user_id(user_id)
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректный ID пользователя.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_admin_'))
def remove_admin(call):
    user_id = int(call.data.split('_')[2])
    remove_role(user_id, 'admin')
    bot.send_message(call.message.chat.id, f"Пользователь с ID {user_id} удален из администраторов.")
    list_admins(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_worker_'))
def remove_worker(call):
    user_id = int(call.data.split('_')[2])
    
    # Снимаем роль 'worker' с пользователя
    remove_role(user_id, 'worker')
    
    # Отправляем сообщение пользователю о снятии роли
    bot.send_message(user_id, "🔓 <b>Ваша роль 'worker' была снята. Доступ к функционалу закрыт.</b>", parse_mode='HTML')
    
    # Показываем пользователю клавиатуру с кнопкой 'Запросить доступ'
    show_pending_menu_by_user_id(user_id)

    # Сообщаем администратору об успешном снятии роли
    bot.send_message(call.message.chat.id, f"Пользователь с ID {user_id} был удалён из списка работников.")
    
    # Обновляем список работников
    list_workers(call.message)

    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: message.text == '🔄 Начать работу')
def start_work(message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {'whatsapp': [], 'telegram': [], 'start_time': None, 'sms_requests': {}}
    user_data[user_id]['start_time'] = datetime.datetime.now()

    user_roles = db.fetch_one("SELECT roles FROM users WHERE user_id = ?", (user_id,))
    if user_roles and 'admin' in user_roles[0].split(','):
        show_admin_main_menu(message)
    else:
        show_main_menu(message)

@bot.message_handler(func=lambda message: message.text == '➕ Добавить номера')
def add_numbers(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("WhatsApp", callback_data="add_whatsapp")
    btn2 = types.InlineKeyboardButton("Telegram", callback_data="add_telegram")
    markup.add(btn1, btn2)
    back_button = types.InlineKeyboardButton('🔙 Назад', callback_data='go_back')
    markup.add(back_button)
    
    try:
        retry_request(bot.send_message, message.chat.id, "📲 Выберите, куда добавить номер:", reply_markup=markup)
    except (ReadTimeout, ConnectionError):
        bot.send_message(message.chat.id, "Ошибка сети. Пожалуйста, попробуйте снова позже.")

@bot.callback_query_handler(func=lambda call: call.data in ['add_whatsapp', 'add_telegram'])
def choose_service(call):
    service = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"Введите список номеров для {service.capitalize()} в формате 9123456789, каждый номер с новой строки:")
    bot.register_next_step_handler(msg, process_numbers, service)
    show_back_button(call.message)
    
def process_numbers(message, service):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {'whatsapp': [], 'telegram': [], 'start_time': None, 'sms_requests': {}}
    
    numbers = message.text.split('\n')
    valid_numbers = []
    invalid_numbers = 0
    
    current_numbers_count = len(user_data[user_id][service])
    max_numbers_limit = 25 if service == 'whatsapp' else 50

    for number in numbers:
        if len(number) == 10 and number.isdigit():
            if current_numbers_count < max_numbers_limit:
                valid_numbers.append({'number': number, 'timestamp': datetime.datetime.now(), 'user_id': user_id})
                current_numbers_count += 1
            else:
                break
        else:
            invalid_numbers += 1

    # Добавление валидных номеров в базу данных
    for number in valid_numbers:
        db.execute_query("INSERT INTO numbers (number, service, user_id, add_date, add_time) VALUES (?, ?, ?, ?, ?)",
                         (number['number'], service, user_id, number['timestamp'].date(), number['timestamp'].time().strftime('%H:%M:%S')))
    
    # Считываем актуальное количество активных номеров для пользователя из базы данных
    active_numbers_count = db.fetch_one("SELECT COUNT(*) FROM numbers WHERE user_id = ? AND success = 0", (user_id,))[0]
    
    response = f"✅ Обработка номеров {service.capitalize()} завершена!\n\n"
    response += f"➕ Добавлено записей: {len(valid_numbers)}\n"
    response += f"❌ Не удалось распознать: {invalid_numbers}\n"
    response += f"🔢 Обработано записей: {len(numbers)}\n"
    response += f"📋 Ваших номеров в очереди: {active_numbers_count}\n"  # Отображаем актуальное количество активных номеров
    bot.send_message(message.chat.id, response)
    show_back_button(message)

@bot.message_handler(func=lambda message: message.text == '📊 Профиль')
def show_profile(message):
    user_id = message.from_user.id

    # Проверяем, существует ли пользователь в user_data
    if user_id not in user_data:
        bot.send_message(message.chat.id, "Сначала начните работу, чтобы видеть статистику.")
        return

    # Считываем количество удачных и слетевших номеров для пользователя
    whatsapp_success = db.fetch_one("SELECT COUNT(*) FROM numbers WHERE user_id = ? AND service = 'whatsapp' AND success = 1", (user_id,))[0]
    whatsapp_failed = db.fetch_one("SELECT COUNT(*) FROM numbers WHERE user_id = ? AND service = 'whatsapp' AND failed = 1", (user_id,))[0]
    whatsapp_total = db.fetch_one("SELECT COUNT(*) FROM numbers WHERE user_id = ? AND service = 'whatsapp'", (user_id,))[0]

    telegram_success = db.fetch_one("SELECT COUNT(*) FROM numbers WHERE user_id = ? AND service = 'telegram' AND success = 1", (user_id,))[0]
    telegram_failed = db.fetch_one("SELECT COUNT(*) FROM numbers WHERE user_id = ? AND service = 'telegram' AND failed = 1", (user_id,))[0]
    telegram_total = db.fetch_one("SELECT COUNT(*) FROM numbers WHERE user_id = ? AND service = 'telegram'", (user_id,))[0]

    # Получаем цены из базы данных (предполагается, что у вас есть функция db.get_price)
    whatsapp_price = db.get_price('whatsapp')
    telegram_price = db.get_price('telegram')

    # Вычисляем заработок
    whatsapp_earnings = whatsapp_success * whatsapp_price
    telegram_earnings = telegram_success * telegram_price

    # Формируем ответное сообщение с корректными данными
    response = f"🧸 Вы {message.from_user.username}\n"
    response += f"Статистика за {datetime.date.today().strftime('%d-%m-%Y')}\n"
    response += f"🟢 WhatsApp:\n"
    response += f"Удачных: {whatsapp_success}\n"
    response += f"Слетевших: {whatsapp_failed}\n"
    response += f"Всего: {whatsapp_total}\n"
    response += f"За сегодня вы заработали: {whatsapp_earnings}$\n\n"  # Добавлена строка о заработке

    response += f"🔵 Telegram:\n"
    response += f"Удачных: {telegram_success}\n"
    response += f"Слетевших: {telegram_failed}\n"
    response += f"Всего: {telegram_total}\n"
    response += f"За сегодня вы заработали: {telegram_earnings}$\n"  # Добавлена строка о заработке

    bot.send_message(message.chat.id, response)

@bot.message_handler(func=lambda message: message.text == '📋 Добавленные номера')
def show_added_numbers(message):
    user_id = message.from_user.id
    if user_id not in user_data:
        bot.send_message(message.chat.id, "Сначала начните работу, чтобы видеть добавленные номера.")
        return

    page = 0
    show_numbers_page(message, user_id, page)

def show_numbers_page(message, user_id, page):
    markup = types.InlineKeyboardMarkup()

    # Фильтруем номера, исключая успешные и слетевшие
    numbers = db.fetch_all(
        "SELECT number_id, number, add_date, add_time, service FROM numbers WHERE user_id = ? AND success = 0 AND failed = 0", 
        (user_id,)
    )

    if not numbers:
        bot.send_message(message.chat.id, "У вас нет добавленных номеров.")
        return

    start_index = page * 4
    end_index = start_index + 4
    numbers_page = numbers[start_index:end_index]

    for entry in numbers_page:
        number_id = entry[0]
        number = entry[1]
        timestamp = f"{entry[2]} {entry[3]}"
        service = entry[4]

        service_emoji = "🟢" if service == "whatsapp" else "🔵"
        btn_text = f"{service_emoji} {timestamp} - {number}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"confirm_delete_{number_id}"))

    if start_index > 0:
        markup.add(types.InlineKeyboardButton('⬅️ Назад', callback_data=f'prev_page_{page-1}'))
    if end_index < len(numbers):
        markup.add(types.InlineKeyboardButton('➡️ Вперед', callback_data=f'next_page_{page+1}'))

    markup.add(types.InlineKeyboardButton('🔙 Назад', callback_data='go_back'))
    bot.send_message(message.chat.id, "Ваши номера:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_delete_'))
def confirm_delete_number(call):
    number_id = call.data.split('_')[2]
    markup = types.InlineKeyboardMarkup()
    btn_yes = types.InlineKeyboardButton('Да', callback_data=f'delete_number_{number_id}')
    btn_no = types.InlineKeyboardButton('Нет', callback_data='cancel_delete')
    markup.add(btn_yes, btn_no)
    bot.send_message(call.message.chat.id, f"Вы точно хотите удалить номер с ID {number_id} из очереди?", reply_markup=markup)
    bot.answer_callback_query(call.id)

def print_numbers_table():
    rows = db.fetch_all("SELECT * FROM numbers")
    for row in rows:
        print(row)

def delete_number_entry(number, add_date, add_time):
    print(f"Deleting number {number} with add_date {add_date} and add_time {add_time}")
    db.execute_query("DELETE FROM numbers WHERE number = ? AND add_date = ? AND add_time = ?", (number, add_date, add_time))
    # Verify if the number is deleted
    result = db.fetch_one("SELECT * FROM numbers WHERE number = ? AND add_date = ? AND add_time = ?", (number, add_date, add_time))
    if result:
        print(f"Number {number} still exists in the database: {result}")
    else:
        print(f"Number {number} successfully deleted from the database.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_number_'))
def delete_number(call):
    try:
        number_id = call.data.split('_')[2]
        user_id = call.from_user.id

        number_data = db.fetch_one("SELECT user_id FROM numbers WHERE number_id = ?", (number_id,))
        if number_data and number_data[0] == user_id:
            db.execute_query("DELETE FROM numbers WHERE number_id = ?", (number_id,))
            remaining_number = db.fetch_one("SELECT * FROM numbers WHERE number_id = ?", (number_id,))
            if not remaining_number:
                bot.send_message(user_id, f"Номер с ID {number_id} успешно удалён из очереди!")
                update_message_with_numbers(call.message, user_id)
            else:
                bot.send_message(user_id, "Не удалось удалить номер.")
        else:
            bot.send_message(user_id, "Вы не можете удалить этот номер, так как он вам не принадлежит.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"Произошла ошибка при удалении номера: {e}")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_delete')
def cancel_delete(call):
    bot.send_message(call.message.chat.id, "Удаление отменено.")
    show_numbers_page(call.message, call.from_user.id, 0)


@bot.callback_query_handler(func=lambda call: call.data.startswith('prev_page_') or call.data.startswith('next_page_'))
def handle_pagination(call):
    user_id = call.from_user.id
    page = int(call.data.split('_')[-1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    show_numbers_page(call.message, user_id, page)

@bot.message_handler(func=lambda message: message.text == '⏹️ Закончить работу')
def end_work(message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {'whatsapp': [], 'telegram': [], 'start_time': None, 'sms_requests': {}}

    user_data[user_id]['start_time'] = None
    user_data[user_id]['whatsapp'] = []
    user_data[user_id]['telegram'] = []

    # Удаление всех номеров пользователя из базы данных
    db.execute_query("DELETE FROM numbers WHERE user_id = ?", (user_id,))
    
    bot.send_message(message.chat.id, "⏹️ Работа завершена. Все ваши номера удалены из очереди.")
    
    # Обновление сообщения с кнопками номеров
    remove_all_number_buttons(message)

def remove_all_number_buttons(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('🔙 Назад', callback_data='go_back'))
    bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=markup)

@bot.message_handler(commands=['rm'])
def remove_numbers(message):
    numbers = message.text.split()[1:]
    for number in numbers:
        db.execute_query("DELETE FROM numbers WHERE number = ?", (number,))
        bot.send_message(message.chat.id, f"Номер {number} удален из базы данных.")

@bot.message_handler(func=lambda message: message.text.lower() in ['вотс', 'телега'])
@group_required
def handle_purchase(message):
    group_id = get_group_id(message)
    service = 'whatsapp' if message.text.lower() == 'вотс' else 'telegram'
    
    queue_data = db.fetch_all("SELECT * FROM numbers WHERE service = ? AND issued_to IS NULL AND group_id IS NULL", (service,))
    
    if queue_data:
        number_entry = random.choice(queue_data)
        number = number_entry[1]

        db.execute_query("UPDATE numbers SET issued_to = ?, issued_time = ?, group_id = ?, success = 0, failed = 0 WHERE number = ?",
                         (message.from_user.id, datetime.datetime.now(), group_id, number))

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton('Запросить СМС', callback_data=f'request_sms_{number}'),
            types.InlineKeyboardButton('Замена', callback_data=f'replace_number_{number}'),
        )

        bot.send_message(message.chat.id, f"📱 <b>Номер:</b> <code>{number}</code>", reply_markup=markup)

        bot.send_message(message.from_user.id, f"📲 <b>Номер {number} был выдан вам.</b>")
        db.increment_counter()
        db.update_stats(service, success=False)

        timer = threading.Timer(120, return_number_to_queue, args=(number, message.chat.id))
        active_timers[number] = timer
        timer.start()
    else:
        bot.send_message(message.chat.id, f"☹️ <b>Нет доступных номеров для {service.capitalize()}.</b>")

def return_number_to_queue(number, chat_id):
    number_data = db.fetch_one("SELECT issued_to, success, failed, group_id FROM numbers WHERE number = ?", (number,))
    
    if number_data:
        issued_to, success, failed, group_id = number_data
        
        if failed == 1:
            return
        
        if success == 0:
            db.execute_query("UPDATE numbers SET issued_to = NULL, issued_time = NULL, group_id = NULL WHERE number = ? AND success = 0", (number,))
            bot.send_message(group_id, f"Время на запрос СМС истекло. Номер {number} возвращен в очередь.")

    if number in active_timers:
        del active_timers[number]

def replace_number_after_timeout(message, number, worker_id):
    issued_to = db.fetch_one("SELECT issued_to FROM numbers WHERE number = ? AND success = 0", (number,))
    if issued_to:
        issued_to = issued_to[0]
        db.execute_query("UPDATE numbers SET issued_to = NULL, issued_time = NULL WHERE number = ? AND success = 0", (number,))
        bot.send_message(worker_id, f"Время на отправку сообщения для номера {number} истекло. Номер возвращен в очередь.")
        
        service_data = db.fetch_one("SELECT service FROM numbers WHERE number = ?", (number,))
        if service_data:
            service = service_data[0]
            queue_data = db.fetch_all("SELECT number FROM numbers WHERE service = ? AND issued_to IS NULL", (service,))
            if queue_data:
                new_number = random.choice(queue_data)[0]
                db.execute_query("UPDATE numbers SET issued_to = ?, issued_time = ? WHERE number = ?",
                                 (issued_to, datetime.datetime.now(), new_number))
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton('Запросить СМС', callback_data=f'request_sms_{new_number}'),
                    types.InlineKeyboardButton('Замена', callback_data=f'replace_number_{new_number}'),
                )
                bot.send_message(issued_to, f"Ваш номер был заменен. Новый номер: <code>{new_number}</code>", reply_markup=markup)
                bot.send_message(worker_id, f"Номер {new_number} был выдан пользователю {issued_to}.")
                db.increment_counter()
                db.update_stats(service, success=False)
            else:
                bot.send_message(issued_to, f"Нет доступных номеров для {service.capitalize()} для замены.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('request_sms_'))
def request_sms(call):
    global request_counter
    number = call.data.split('_')[2]
    buyer_id = call.from_user.id

    number_data = db.fetch_one("SELECT issued_to, group_id FROM numbers WHERE number = ?", (number,))
    if not number_data:
        bot.send_message(call.message.chat.id, "Ошибка: Номер не найден в базе данных.")
        return
    
    issued_to, group_id = number_data

    if issued_to != buyer_id:
        bot.send_message(call.message.chat.id, "Ошибка: Этот номер не принадлежит вам.")
        return

    worker_id = db.get_worker_id_by_number(number)
    
    if worker_id:
        request_counter += 1
        request_id = request_counter

        if worker_id not in request_ids:
            request_ids[worker_id] = {}

        request_ids[worker_id][request_id] = {
            'number': number,
            'worker_id': worker_id,
            'target_user_id': buyer_id,
            'group_id': group_id,
            'message_id': None,
            'status': 'pending'
        }

        service = db.get_service_by_number(number)
        service_emoji = "🟢" if service == "whatsapp" else "🔵"

        # Отправляем сообщение работнику с запросом СМС
        request_msg = bot.send_message(
            worker_id,
            f"🔔 <b>Напишите смс к номеру {service_emoji} {service.capitalize()} <code>{number}</code></b>\n\n"
            f"❗ <b>У вас есть 2 минуты!</b>\n\n"
            f"🆔 <b>ID: {request_id}</b>",
            reply_markup=worker_sms_markup(number),
            parse_mode='HTML'
        )

        request_ids[worker_id][request_id]['message_id'] = request_msg.message_id

        # Останавливаем таймер, если он существует
        if number in active_timers:
            active_timers[number].cancel()
            del active_timers[number]

        bot.send_message(buyer_id, f"Запрос на получение СМС по номеру <code>{number}</code> отправлен.", parse_mode='HTML')

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton('Запросить СМС (неактивно)', callback_data=f'request_sms_{number}', disable_web_page_preview=True))
        markup.add(types.InlineKeyboardButton('Замена', callback_data=f'replace_number_{number}'))

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, "Ошибка: Номер не привязан к работнику.")

    bot.answer_callback_query(call.id)

def worker_sms_markup(number):
    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_button = types.InlineKeyboardButton('Отказаться', callback_data=f'cancel_sms_{number}')
    markup.add(cancel_button)
    return markup

def receive_sms(message, request_id):
    worker_id = message.from_user.id

    # Проверяем, есть ли запрос с указанным request_id для данного работника
    if worker_id in request_ids and request_id in request_ids[worker_id]:
        request_info = request_ids[worker_id][request_id]
        number = request_info['number']
        target_user_id = request_info['target_user_id']
        group_id = request_info['group_id']  # Получаем ID группы из запроса

        # Проверяем, что ответное сообщение соответствует ожидаемому запросу
        if message.reply_to_message and message.reply_to_message.message_id == request_info['message_id']:
            issued_to = db.fetch_one("SELECT issued_to FROM numbers WHERE number = ?", (number,))

            # Проверяем, принадлежит ли номер пользователю, который запрашивал SMS
            if issued_to and issued_to[0] == target_user_id:
                response = f"Номер: <a href='tel:{number}'>{number}</a>\n<b>SMS:</b> {message.text}\n+{db.get_counter()}"
                markup = telebot.types.InlineKeyboardMarkup(row_width=1)
                decrement_button = telebot.types.InlineKeyboardButton('❌Слёт', callback_data=f'decrement_counter_{number}')
                markup.add(decrement_button)

                # Отправляем сообщение в ту же группу, где был запрошен номер
                sent_msg = bot.send_message(group_id, response, reply_markup=markup, parse_mode='HTML')

                if 'successful' not in recently_issued_numbers:
                    recently_issued_numbers['successful'] = []
                recently_issued_numbers['successful'].append(number)

                # Деактивируем кнопку через 100 секунд
                threading.Timer(100, deactivate_decrement_button, args=(group_id, sent_msg.message_id, number)).start()

                # Удаляем запрос из списка активных
                del request_ids[worker_id][request_id]

                # Уведомляем работника и пользователя
                bot.send_message(worker_id, "🔼 <b>Код был отправлен пользователю</b>")
                bot.send_message(target_user_id, f"✉️ <b>Ваше сообщение по номеру <a href='tel:{number}'>{number}</a> было отправлено в группу.</b>")
            else:
                bot.send_message(message.chat.id, "Номер не найден или не привязан к пользователю.")
        else:
            bot.send_message(message.chat.id, "СМС не соответствует ожиданиям.")
    else:
        bot.send_message(message.chat.id, "Запрос не найден или уже обработан.")

@bot.message_handler(func=lambda message: message.reply_to_message is not None)
def handle_reply(message):
    replied_message_id = message.reply_to_message.message_id

    # Ищем запрос с таким же message_id
    for user_id, requests in request_ids.items():
        for request_id, request_info in requests.items():
            if request_info['message_id'] == replied_message_id and request_info['status'] == 'pending':
                receive_sms(message, request_id)
                return

    bot.send_message(message.chat.id, "Запрос на получение СМС не найден или уже обработан.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('replace_number_'))
def replace_number(call):
    number = call.data.split('_')[2]
    service_data = db.fetch_one("SELECT service, group_id FROM numbers WHERE number = ?", (number,))
    
    if service_data:
        service, group_id = service_data
        
        all_numbers = db.fetch_all("SELECT number FROM numbers WHERE service = ? AND issued_to IS NULL", (service,))
        available_numbers = [entry[0] for entry in all_numbers if entry[0] not in recently_issued_numbers.get(service, [])]

        if not available_numbers:
            available_numbers = [entry[0] for entry in all_numbers]
            recently_issued_numbers[service] = []

        new_number = random.choice(available_numbers)
        recently_issued_numbers[service].append(new_number)

        if len(recently_issued_numbers[service]) > len(all_numbers):
            recently_issued_numbers[service].pop(0)

        db.execute_query("UPDATE numbers SET issued_to = ?, issued_time = ?, group_id = ? WHERE number = ?",
                         (call.from_user.id, datetime.datetime.now(), group_id, new_number))
        db.execute_query("UPDATE numbers SET issued_to = NULL, issued_time = NULL, group_id = NULL WHERE number = ?", (number,))

        markup = types.InlineKeyboardMarkup(row_width=1)
        sms_button = types.InlineKeyboardButton('Запросить СМС', callback_data=f'request_sms_{new_number}')
        replace_button = types.InlineKeyboardButton('Замена', callback_data=f'replace_number_{new_number}')
        markup.add(sms_button, replace_button)

        bot.edit_message_text(f"🔄 <b>Ваш номер был заменен. Новый номер:</b> <code>{new_number}</code>", 
                              call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    else:
        bot.send_message(call.message.chat.id, "Ошибка: не удалось найти сервис для этого номера.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_sms_'))
def cancel_sms(call):
    number = call.data.split('_')[2]
    worker_id = call.from_user.id

    number_data = db.fetch_one("SELECT issued_to, group_id FROM numbers WHERE number = ?", (number,))
    if not number_data:
        bot.send_message(call.message.chat.id, "Ошибка: Номер не найден в базе данных.")
        return
    
    issued_to, group_id = number_data

    if issued_to == worker_id:
        db.execute_query("UPDATE numbers SET issued_to = NULL, issued_time = NULL, group_id = NULL WHERE number = ?", (number,))
        bot.send_message(worker_id, f"↩️ <b>Вы отказались от обработки номера {number}. Номер возвращен в очередь.</b>")
        bot.send_message(group_id, f"Работник отказался от обработки номера {number}. Номер возвращен в очередь.")
    else:
        bot.answer_callback_query(call.id, text="Вы не можете отказаться от номера, который не принадлежит вам.")

    bot.answer_callback_query(call.id)

def auto_clear():
    while True:
        now = datetime.datetime.now()
        if now.hour == 2 and now.minute == 0:
            db.execute_query("DELETE FROM numbers")
            db.reset_counter()
            for user_id in user_data:
                user_data[user_id]['whatsapp'] = []
                user_data[user_id]['telegram'] = []
            bot.send_message(db.ADMIN_ID, f"🔄 <b>Автоматический сброс номеров завершен.</b>")
            time.sleep(60)


Thread(target=auto_clear).start()

def show_back_button(message):
    markup = telebot.types.InlineKeyboardMarkup()
    back_button = telebot.types.InlineKeyboardButton('🔙 Назад', callback_data='go_back')
    markup.add(back_button)
    bot.send_message(message.chat.id, "🔙 <b>Нажмите 'Назад' для возврата в главное меню.</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'go_back')
def handle_back(call):
    show_main_menu(call.message)
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: message.text == 'Подать заявку на доступ')
def request_access(message):
    user_id = message.from_user.id
    bot.send_message(config.ADMIN_ID, f"🛎 <b>Новая заявка на доступ от пользователя @{message.from_user.username} (ID: {user_id}).</b>", reply_markup=admin_approval_markup(user_id))
    bot.send_message(message.chat.id, "✅ <b>Ваша заявка отправлена. Ожидайте подтверждения.</b>")


@bot.message_handler(func=lambda message: message.text == 'Мои заявки')
def view_requests(message):
    user_id = message.from_user.id
    if str(user_id) == config.ADMIN_ID:
        pending_requests = db.fetch_all("SELECT * FROM requests WHERE status = 'pending'")
        if pending_requests:
            response = "📝 <b>Заявки ожидающие подтверждения:</b>\n\n"
            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            for req in pending_requests:
                response += f"Пользователь: @{req['username']} (ID: {req['user_id']})\n"
                markup.add(telebot.types.InlineKeyboardButton(f"Заявка от @{req['username']}", callback_data=f"show_request_{req['user_id']}"))
            bot.send_message(message.chat.id, response, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "📭 <b>Нет заявок ожидающих подтверждения.</b>")
    else:
        bot.send_message(message.chat.id, "🚫 <b>У вас нет прав на просмотр заявок.</b>")

@bot.callback_query_handler(func=lambda call: call.data.startswith('show_request_'))
def show_request(call):
    user_id = int(call.data.split('_')[2])
    request = db.fetch_one("SELECT * FROM requests WHERE user_id = ? AND status = 'pending'", (user_id,))
    if request:
        response = f"🛎 <b>Новая заявка от @{request['username']} (ID: {request['user_id']})</b>\n"
        response += "Одобрить или Отказать?"
        bot.send_message(call.message.chat.id, response, reply_markup=admin_approval_markup(user_id))
    else:
        bot.send_message(call.message.chat.id, "Заявка уже обработана.")
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['admin_stats'])
def admin_stats(message):
    user_id = message.from_user.id
    if str(user_id) == config.ADMIN_ID:
        response = "📊 <b>Статистика пользователей:</b>\n"
        for user in user_data:
            response += f"/uid{user} [@{bot.get_chat(user).username}]: WhatsApp {len(user_data[user]['whatsapp'])}/0/0/0/0 Telegram: {len(user_data[user]['telegram'])}/0\n"
        bot.send_message(message.chat.id, response)
    else:
        bot.send_message(message.chat.id, "🚫 <b>У вас нет прав на просмотр этой информации.</b>")

@bot.callback_query_handler(func=lambda call: call.data.startswith('decrement_counter_'))
def decrement_counter_handler(call):
    number = call.data.split('_')[2]
    number_info = db.fetch_one("SELECT number_id, user_id, group_id FROM numbers WHERE number = ?", (number,))
    
    if number_info:
        number_id, worker_id, group_id = number_info

        db.decrement_counter()
        db.execute_query("UPDATE numbers SET failed = 1 WHERE number_id = ?", (number_id,))

        try:
            bot.edit_message_text(
                text=f"📱 <b>Номер:</b> <code>{number}</code>\n<b>SMS:</b> 1222\n-1",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='HTML'
            )
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Error editing message: {e}")

        if worker_id:
            service = db.get_service_by_number(number)
            bot.send_message(worker_id, f"⚠️ <b>Номер {service.capitalize()} <code>{number}</code> слетел! (-1)</b>", parse_mode='HTML')
            bot.send_message(group_id, f"Номер <code>{number}</code> слетел.")
    bot.answer_callback_query(call.id)

def finalize_number_status(number, chat_id, message_id):
    number_info = db.fetch_one("SELECT success, failed, issued_to, user_id, group_id FROM numbers WHERE number = ?", (number,))

    if number_info:
        success, failed, issued_to, worker_id, group_id = number_info

        if success == 0 and failed == 0:
            db.mark_successful(number)
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)

            if worker_id:
                service = db.get_service_by_number(number)
                bot.send_message(worker_id, f"✅ <b>Ваш номер {service.capitalize()} <code>{number}</code> был успешно засчитан! (+1)</b>", parse_mode='HTML')
                bot.send_message(group_id, f"Номер <code>{number}</code> успешно засчитан.")
        else:
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)

def update_message_with_numbers(chat_id, user_id):
    numbers = db.fetch_all(
        "SELECT number_id, number, add_date, add_time, service FROM numbers WHERE issued_to = ? AND success = 0 AND failed = 0", 
        (user_id,)
    )
    
    markup = telebot.types.InlineKeyboardMarkup()

    if numbers:
        for entry in numbers:
            number_id = entry[0]
            number = entry[1]
            timestamp = f"{entry[2]} {entry[3]}"
            service = entry[4]

            service_emoji = "🟢" if service == "whatsapp" else "🔵"
            btn_text = f"{service_emoji} {timestamp} - {number}"
            markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"confirm_delete_{number_id}"))

    markup.add(telebot.types.InlineKeyboardButton('🔙 Назад', callback_data='go_back'))

    try:
        bot.edit_message_reply_markup(chat_id, chat_id, reply_markup=markup)
    except telebot.apihelper.ApiTelegramException as e:
        print(f"Error editing message: {e}")

@bot.message_handler(commands=['clear'])
def clear_group_chat(message):
    chat_id = message.chat.id

    if not db.is_admin(message.from_user.id):
        bot.send_message(chat_id, "🚫 <b>У вас нет прав на выполнение этой команды.</b>")
        return

    try:
        # Получаем ID последнего сообщения
        last_message_id = bot.get_updates()[-1].message.message_id

        # Удаляем сообщения в цикле, пока не достигнем ограничения по времени
        while True:
            try:
                bot.delete_message(chat_id, last_message_id)
                last_message_id -= 1 
            except telebot.apihelper.ApiTelegramException as e:
                if "message to delete not found" in str(e):
                    # Достигли ограничения по времени, выходим из цикла
                    break
                else:
                    print(f"Error deleting message {last_message_id}: {e}")

    except Exception as e:
        bot.send_message(chat_id, f"Ошибка при очистке чата: {e}")
        return

    bot.send_message(chat_id, "🧹 <b>Чат успешно очищен.</b>")

def deactivate_decrement_button(chat_id, message_id, number):
    number_info = db.fetch_one("SELECT success, failed, user_id, group_id FROM numbers WHERE number = ?", (number,))
    if number_info:
        success, failed, user_id, group_id = number_info
        if success == 0 and failed == 0:
            markup = types.InlineKeyboardMarkup()
            btn = types.InlineKeyboardButton('❌Слёт (неактивна)', callback_data=f'decrement_counter_{number}', disable_web_page_preview=True)
            markup.add(btn)
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
            finalize_number_status(number, chat_id, message_id)
        elif failed == 1:
            bot.send_message(chat_id, f"Номер {number} уже был помечен как неудачный.")
        else:
            bot.send_message(chat_id, f"Номер {number} уже был помечен как успешный.")

if __name__ == '__main__':
    add_role(config.ADMIN_ID, 'admin')
    try:
        bot.polling(none_stop=True, timeout=30)
    except KeyboardInterrupt:
        pass 