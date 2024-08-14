from telebot import types
from utils import db, config, bot

# Обработчики команд администратора
@bot.message_handler(commands=['admin_stats'])
def admin_stats(message):
    user_id = message.from_user.id
    if str(user_id) == config.ADMIN_ID:
        response = "📊 Статистика пользователей:\n"
        for user in db.fetch_all("SELECT user_id, username FROM users"):
            response += f"/uid{user[0]} [@{user[1]}]: WhatsApp {db.get_user_stat(user[0], 'whatsapp')}/Telegram: {db.get_user_stat(user[0], 'telegram')}\n"
        bot.send_message(message.chat.id, response)
    else:
        bot.send_message(message.chat.id, "У вас нет прав на просмотр этой информации.")

@bot.message_handler(commands=['setbalance'])
def set_balance(message):
    user_id = message.from_user.id
    if str(user_id) != config.ADMIN_ID:
        bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")
        return

    try:
        _, balance, target_id = message.text.split()
        balance = float(balance)
        target_id = int(target_id)
    except ValueError:
        bot.send_message(message.chat.id, "Использование: /setbalance {balance} {id}")
        return

    db.execute_query("UPDATE users SET earnings = ? WHERE user_id = ?", (balance, target_id))
    bot.send_message(message.chat.id, f"Баланс пользователя {target_id} установлен на {balance}.")

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
        db.add_role(user_id, 'worker')
        bot.send_message(message.chat.id, f"Пользователь с ID {user_id} добавлен в работники.")
        show_main_menu_by_user_id(user_id)
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректный ID пользователя.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_worker_'))
def remove_worker(call):
    user_id = int(call.data.split('_')[2])
    db.remove_role(user_id, 'worker')
    bot.send_message(call.message.chat.id, f"Пользователь с ID {user_id} удален из работников.")
    list_workers(call.message)

@bot.callback_query_handler(func=lambda call: call.data == 'add_admin')
def add_admin(call):
    msg = bot.send_message(call.message.chat.id, "Введите ID пользователя для добавления в администраторы:")
    bot.register_next_step_handler(msg, process_add_admin)

def process_add_admin(message):
    try:
        user_id = int(message.text)
        db.add_role(user_id, 'admin')
        bot.send_message(message.chat.id, f"Пользователь с ID {user_id} добавлен в администраторы.")
        show_admin_main_menu_by_user_id(user_id)
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректный ID пользователя.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_admin_'))
def remove_admin(call):
    user_id = int(call.data.split('_')[2])
    db.remove_role(user_id, 'admin')
    bot.send_message(call.message.chat.id, f"Пользователь с ID {user_id} удален из администраторов.")
    list_admins(call.message)
