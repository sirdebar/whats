import random
from telebot import types
from utils import db, bot

cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11]  # 10 - валет, дама, король; 11 - туз

@bot.message_handler(commands=['casino'])
def casino(message):
    markup = types.InlineKeyboardMarkup()
    btn_blackjack = types.InlineKeyboardButton("Блекджек", callback_data="game_blackjack")
    btn_roulette = types.InlineKeyboardButton("Рулетка", callback_data="game_roulette")
    markup.add(btn_blackjack, btn_roulette)
    bot.send_message(message.chat.id, "Выберите игру:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('game_'))
def game_selection(call):
    if call.data == "game_blackjack":
        send_blackjack_rules(call.message)
    elif call.data == "game_roulette":
        send_roulette_rules(call.message)

def send_blackjack_rules(message):
    rules = ("Правила игры Блекджек:\n"
             "Цель игры - набрать 21 очко или близкое к этому число, не превышая его.\n"
             "Каждая карта имеет свое значение: числовые карты по номиналу, картинки - 10 очков, туз - 1 или 11 очков.")
    markup = types.InlineKeyboardMarkup()
    btn_next = types.InlineKeyboardButton("Далее", callback_data="bet_blackjack")
    markup.add(btn_next)
    bot.send_message(message.chat.id, rules, reply_markup=markup)

def send_roulette_rules(message):
    rules = ("Правила игры Рулетка:\n"
             "Цель игры - угадать номер или цвет, на котором остановится шарик.\n"
             "Можно ставить на номера, цвета или группы чисел.")
    markup = types.InlineKeyboardMarkup()
    btn_next = types.InlineKeyboardButton("Далее", callback_data="bet_roulette")
    markup.add(btn_next)
    bot.send_message(message.chat.id, rules, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "bet_blackjack")
def bet_blackjack(call):
    user_id = call.from_user.id
    earnings = db.fetch_user_earnings(user_id)
    if earnings > 0:
        msg = bot.send_message(call.message.chat.id, "Введите сумму ставки:")
        bot.register_next_step_handler(msg, start_blackjack)
    else:
        bot.send_message(call.message.chat.id, "Недостаточно средств для ставки.")

def start_blackjack(message):
    user_id = message.from_user.id
    try:
        bet = float(message.text)
        if bet <= 0:
            raise ValueError("Ставка должна быть положительным числом.")
    except ValueError as e:
        bot.send_message(message.chat.id, str(e))
        return

    earnings = db.fetch_user_earnings(user_id)
    if bet > earnings:
        bot.send_message(message.chat.id, "Недостаточно средств для ставки.")
        return

    player_hand = [random.choice(cards)]
    dealer_hand = [random.choice(cards)]

    db.execute_query("INSERT OR REPLACE INTO blackjack_game (user_id, player_hand, dealer_hand, bet) VALUES (?, ?, ?, ?)",
                     (user_id, str(player_hand), str(dealer_hand), bet))

    send_blackjack_status(message.chat.id, player_hand, dealer_hand, user_id)

def send_blackjack_status(chat_id, player_hand, dealer_hand, user_id):
    player_score = sum(player_hand)
    dealer_score = dealer_hand[0]
    markup = types.InlineKeyboardMarkup()
    btn_hit = types.InlineKeyboardButton("Взять", callback_data=f"hit_{user_id}")
    btn_stand = types.InlineKeyboardButton("Хватит", callback_data=f"stand_{user_id}")
    markup.add(btn_hit, btn_stand)
    bot.send_message(chat_id, f"Ваши карты: {player_hand} (очков: {player_score})\nКарты дилера: {dealer_hand[0]}\nВыберите действие:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('hit_'))
def hit(call):
    user_id = int(call.data.split('_')[1])
    game = db.fetch_one("SELECT player_hand, dealer_hand, bet FROM blackjack_game WHERE user_id = ?", (user_id,))
    if game:
        player_hand = eval(game[0])
        dealer_hand = eval(game[1])
        bet = game[2]

        player_hand.append(random.choice(cards))

        if sum(player_hand) > 21:
            bot.send_message(call.message.chat.id, f"Ваши карты: {player_hand} (очков: {sum(player_hand)})\nПеребор! Вы проиграли.")
            db.update_earnings(user_id, -bet)
            db.execute_query("DELETE FROM blackjack_game WHERE user_id = ?", (user_id,))
        else:
            send_blackjack_status(call.message.chat.id, player_hand, dealer_hand, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stand_'))
def stand(call):
    user_id = int(call.data.split('_')[1])
    game = db.fetch_one("SELECT player_hand, dealer_hand, bet FROM blackjack_game WHERE user_id = ?", (user_id,))
    if game:
        player_hand = eval(game[0])
        dealer_hand = eval(game[1])
        bet = game[2]

        while sum(dealer_hand) < 17:
            dealer_hand.append(random.choice(cards))

        player_score = sum(player_hand)
        dealer_score = sum(dealer_hand)

        result_msg = f"Ваши карты: {player_hand} (очков: {player_score})\nКарты дилера: {dealer_hand} (очков: {dealer_score})\n"
        if dealer_score > 21 or player_score > dealer_score:
            result_msg += "Вы выиграли!"
            db.update_earnings(user_id, bet)
        else:
            result_msg += "Вы проиграли."
            db.update_earnings(user_id, -bet)

        bot.send_message(call.message.chat.id, result_msg)
        db.execute_query("DELETE FROM blackjack_game WHERE user_id = ?", (user_id,))

@bot.callback_query_handler(func=lambda call: call.data == "bet_roulette")
def bet_roulette(call):
    user_id = call.from_user.id
    earnings = db.fetch_user_earnings(user_id)
    if earnings > 0:
        msg = bot.send_message(call.message.chat.id, "Введите сумму ставки:")
        bot.register_next_step_handler(msg, choose_roulette_color)
    else:
        bot.send_message(call.message.chat.id, "Недостаточно средств для ставки.")

def choose_roulette_color(message):
    user_id = message.from_user.id
    try:
        bet = float(message.text)
        if bet <= 0:
            raise ValueError("Ставка должна быть положительным числом.")
    except ValueError as e:
        bot.send_message(message.chat.id, str(e))
        return

    earnings = db.fetch_user_earnings(user_id)
    if bet > earnings:
        bot.send_message(message.chat.id, "Недостаточно средств для ставки.")
        return

    markup = types.InlineKeyboardMarkup()
    btn_red = types.InlineKeyboardButton("Красный", callback_data=f"color_red_{bet}")
    btn_black = types.InlineKeyboardButton("Чёрный", callback_data=f"color_black_{bet}")
    btn_green = types.InlineKeyboardButton("Зелёный", callback_data=f"color_green_{bet}")
    markup.add(btn_red, btn_black, btn_green)
    bot.send_message(message.chat.id, "Выберите цвет:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('color_'))
def spin_roulette(call):
    color = call.data.split('_')[1]
    bet = float(call.data.split('_')[2])
    user_id = call.from_user.id

    emoji_wheel = ["🔴", "⚫️", "🔴", "⚫️", "🟢", "⚫️", "🔴", "⚫️", "🔴"] * 4 + ["🟢"] * 2
    random.shuffle(emoji_wheel)
    spin_position = random.randint(0, len(emoji_wheel) - 1)

    def display_wheel(position, message_id):
        display = emoji_wheel[position:] + emoji_wheel[:position]
        display = display[:6]
        bot.edit_message_text(f"Рулетка крутится:\n{''.join(display)}\n-------^-------", call.message.chat.id, message_id)
        return position + 1 if position < len(emoji_wheel) - 1 else 0

    message_id = bot.send_message(call.message.chat.id, "Рулетка крутится:\n🔴⚫️🔴⚫️🟢⚫️\n-------^-------").message_id

    for _ in range(36):
        spin_position = display_wheel(spin_position, message_id)
        time.sleep(0.1)

    result_color = emoji_wheel[spin_position]
    win = False
    if (color == "red" and result_color == "🔴") or (color == "black" and result_color == "⚫️"):
        win = True
        payout = bet * 2
    elif color == "green" and result_color == "🟢":
        win = True
        payout = bet * 10
    else:
        payout = -bet

    db.update_earnings(user_id, payout)
    result_msg = f"Рулетка остановилась на {result_color}.\n"
    result_msg += "Вы выиграли!" if win else "Вы проиграли."
    bot.send_message(call.message.chat.id, result_msg)
