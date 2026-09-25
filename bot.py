import telebot
from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import libsql

# ===== ТОКЕН =====
TOKEN = "8749981183:AAGptgxFmfqyJ5VKJVA7Vw9__8ScHpflHew"
# =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ===== НАСТРОЙКИ (ЗАМЕНИ НА СВОИ) =====
ADMIN_ID = 986539262           # ← Твой Telegram ID (узнать у @userinfobot)
SUPPORT_NICK = "@AlexeyAzharov"   # ← Юзернейм тех поддержки
AUTHOR_NICK = "@AlexeyAzharov"              # ← Твой личный юзернейм
DONATE_SBP = "+7 960 500-66-76"        # ← Номер для СБП
DONATE_CARD = "2163 5416 0653 1563"    # ← Номер карты
# ======================================

# ===== TURSO =====
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

def get_db():
    """Соединение с Turso (или локальный SQLite как fallback)"""
    if TURSO_URL and TURSO_TOKEN:
        return libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    return libsql.connect("local.db")

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_name TEXT,
            channel_title TEXT,
            added_at TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS seen_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            post_url TEXT,
            seen_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ===== ФУНКЦИИ ПОДПИСОК =====

def add_subscription(user_id, channel_name, channel_title):
    conn = get_db()
    cursor = conn.execute(
        'SELECT id FROM subscriptions WHERE user_id = ? AND channel_name = ?',
        (user_id, channel_name)
    )
    if cursor.fetchone():
        conn.close()
        return False
    conn.execute(
        'INSERT INTO subscriptions (user_id, channel_name, channel_title, added_at) VALUES (?, ?, ?, ?)',
        (user_id, channel_name, channel_title, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    conn.close()
    return True

def get_user_subscriptions(user_id):
    conn = get_db()
    cursor = conn.execute(
        'SELECT channel_name, channel_title FROM subscriptions WHERE user_id = ?',
        (user_id,)
    )
    data = [{'name': row[0], 'title': row[1] or row[0]} for row in cursor.fetchall()]
    conn.close()
    return data

def remove_subscription(user_id, channel_name):
    conn = get_db()
    conn.execute(
        'DELETE FROM subscriptions WHERE user_id = ? AND channel_name = ?',
        (user_id, channel_name)
    )
    conn.commit()
    conn.close()

def mark_post_seen(user_id, post_url):
    conn = get_db()
    conn.execute(
        'INSERT INTO seen_posts (user_id, post_url, seen_at) VALUES (?, ?, ?)',
        (user_id, post_url, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    conn.close()

def is_post_seen(user_id, post_url):
    conn = get_db()
    cursor = conn.execute(
        'SELECT id FROM seen_posts WHERE user_id = ? AND post_url = ?',
        (user_id, post_url)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None

# ===== ПАРСИНГ КАНАЛА =====

def get_channel_posts(channel_name, limit=5):
    try:
        channel_name = channel_name.replace('@', '').strip()
        url = f"https://t.me/s/{channel_name}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        title_el = soup.find('div', class_='tgme_channel_info_header_title')
        title = title_el.get_text(strip=True) if title_el else channel_name
        posts = soup.find_all('div', class_='tgme_widget_message_wrap')
        if not posts:
            return {'title': title, 'posts': [], 'exists': True}
        result_posts = []
        for post in posts[-limit:]:
            post_data = parse_post(post, channel_name)
            if post_data:
                result_posts.append(post_data)
        return {'title': title, 'posts': result_posts, 'exists': True}
    except Exception as e:
        print(f"Ошибка парсинга {channel_name}: {e}")
        return None

def parse_post(post, channel_name):
    try:
        text_el = post.find('div', class_='tgme_widget_message_text')
        text = text_el.get_text(separator='\n', strip=True) if text_el else ""
        time_el = post.find('time')
        date = time_el.get('datetime', '') if time_el else ""
        date_str = ""
        if date:
            try:
                dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
            except:
                date_str = date[:16]
        link_el = post.find('a', class_='tgme_widget_message_date')
        post_url = link_el.get('href', '') if link_el else ""
        photo_url = None
        photo_el = post.find('a', class_='tgme_widget_message_photo_wrap')
        if photo_el:
            style = photo_el.get('style', '')
            if 'url(' in style:
                start = style.find("url('") + 5
                end = style.find("')", start)
                if start > 4 and end > start:
                    photo_url = style[start:end].replace('&amp;', '&')
        video_url = None
        video_el = post.find('video')
        if video_el:
            video_url = video_el.get('src')
        round_video = None
        round_el = post.find('a', class_='tgme_widget_message_roundvideo_wrap')
        if round_el:
            rv = round_el.find('video')
            if rv:
                round_video = rv.get('src')
        if not text and not photo_url and not video_url and not round_video:
            return None
        return {
            'text': text[:800],
            'date': date_str,
            'url': post_url,
            'photo': photo_url,
            'video': video_url,
            'round_video': round_video
        }
    except Exception as e:
        print(f"Ошибка парсинга поста: {e}")
        return None

def extract_channel_name(text):
    text = text.strip()
    if 't.me/' in text:
        parts = text.split('t.me/')
        if len(parts) > 1:
            name = parts[1].split('/')[0].split('?')[0]
            return name
    if text.startswith('@'):
        return text[1:].split()[0]
    if ' ' not in text and len(text) < 50:
        return text
    return None

# ===== КЛАВИАТУРЫ =====

def get_main_keyboard():
    keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        telebot.types.KeyboardButton("➕ Добавить канал"),
        telebot.types.KeyboardButton("🔄 Обновить новости")
    )
    keyboard.add(
        telebot.types.KeyboardButton("📋 Мои каналы"),
        telebot.types.KeyboardButton("⭐ Отзыв")
    )
    keyboard.add(
        telebot.types.KeyboardButton("🛠 Тех поддержка"),
        telebot.types.KeyboardButton("🤝 Сотрудничество")
    )
    keyboard.add(
        telebot.types.KeyboardButton("☕ Поддержи автора")
    )
    return keyboard

def get_start_keyboard():
    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.add(
        telebot.types.InlineKeyboardButton("🚀 Запустить бота", callback_data="start_bot")
    )
    return keyboard

# ===== ВСПОМОГАТЕЛЬНЫЕ ОБРАБОТЧИКИ =====

def process_feedback(message):
    text = message.text.strip()
    user_id = message.from_user.id
    username = message.from_user.username or "unknown"
    try:
        bot.send_message(
            ADMIN_ID,
            f"⭐ *Новый отзыв!*\n\n👤 @{username} (ID: {user_id})\n\n💬 {text}",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка отправки отзыва: {e}")
    bot.send_message(message.chat.id, "✅ Спасибо за отзыв!", reply_markup=get_main_keyboard())

def process_add_channel(message):
    text = message.text.strip()
    user_id = message.from_user.id
    channel_name = extract_channel_name(text)
    if not channel_name:
        bot.send_message(
            message.chat.id,
            "❌ Не могу распознать ссылку. Попробуй ещё раз: /start",
            reply_markup=get_main_keyboard()
        )
        return
    result = get_channel_posts(channel_name, limit=1)
    if not result:
        bot.send_message(
            message.chat.id,
            f"❌ Канал `{channel_name}` не найден или приватный.\n\nУбедись, что он публичный.",
            parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
        return
    added = add_subscription(user_id, channel_name, result['title'])
    if added:
        bot.send_message(
            message.chat.id,
            f"✅ Канал *{result['title']}* (@{channel_name}) добавлен!\n\nНажми *🔄 Обновить новости*, чтобы получать посты.",
            parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
    else:
        bot.send_message(
            message.chat.id,
            f"ℹ️ Канал @{channel_name} уже в ленте.",
            reply_markup=get_main_keyboard()
        )

# ===== КОМАНДЫ =====

@bot.message_handler(commands=['start'])
def start(message):
    first_name = message.from_user.first_name or "друг"
    bot.send_message(
        message.chat.id,
        f"👋 *Привет, {first_name}!*\n\n"
        f"Я — бот-агрегатор новостей.\n\n"
        f"📌 *Что умею:*\n"
        f"• Добавлять публичные Telegram-каналы в твою ленту\n"
        f"• Показывать только новые (непрочитанные) посты\n"
        f"• Работать с фото, видео и текстом\n\n"
        f"Нажми кнопку ниже, чтобы начать 👇",
        parse_mode="Markdown",
        reply_markup=get_start_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == "start_bot")
def start_bot_callback(call):
    first_name = call.from_user.first_name or "друг"
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    bot.send_message(
        call.message.chat.id,
        f"✅ *Отлично, {first_name}!*\n\n"
        f"📌 *Как пользоваться:*\n"
        f"1. Нажми *➕ Добавить канал* и скинь ссылку\n"
        f"2. Нажми *🔄 Обновить новости* — получишь новые посты\n\n"
        f"Используй кнопки внизу 👇",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )
    bot.answer_callback_query(call.id, "Поехали! 🚀")

@bot.message_handler(commands=['help'])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "❓ *Как пользоваться:*\n\n"
        "1. Нажми *➕ Добавить канал*\n"
        "2. Скинь ссылку на канал\n"
        "3. Нажми *🔄 Обновить новости* — получишь новые посты\n"
        "4. Управляй каналами через *📋 Мои каналы*\n\n"
        "⚠️ Работают только *публичные* каналы.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.strip()

    if text == "➕ Добавить канал":
        msg = bot.send_message(
            message.chat.id,
            "📥 Отправь ссылку на канал:\n\n• `https://t.me/durov`\n• `@durov`\n• `durov`",
            parse_mode="Markdown",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, process_add_channel)
        return

    if text == "🔄 Обновить новости":
        subscriptions = get_user_subscriptions(message.from_user.id)
        if not subscriptions:
            bot.send_message(
                message.chat.id,
                "📭 У тебя пока нет каналов.\n\nНажми *➕ Добавить канал*.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return
        msg = bot.send_message(
            message.chat.id,
            f"🔍 Проверяю {len(subscriptions)} канал(ов)...",
            reply_markup=get_main_keyboard()
        )
        new_posts_count = 0
        user_id = message.from_user.id
        for ch in subscriptions:
            result = get_channel_posts(ch['name'], limit=5)
            if not result or not result['posts']:
                continue
            for post in result['posts']:
                post_url = post.get('url', '')
                if not post_url or is_post_seen(user_id, post_url):
                    continue
                caption = f"📢 *{ch['title']}* (@{ch['name']})\n\n"
                if post['text']:
                    caption += post['text']
                if post['date']:
                    caption += f"\n\n🕐 _{post['date']}_"
                if post_url:
                    caption += f"\n🔗 [Открыть пост]({post_url})"
                if len(caption) > 1000:
                    caption = caption[:1000] + "..."
                try:
                    if post['photo']:
                        bot.send_photo(message.chat.id, post['photo'], caption=caption, parse_mode="Markdown")
                    elif post['video'] or post['round_video']:
                        bot.send_video(message.chat.id, post['video'] or post['round_video'], caption=caption, parse_mode="Markdown")
                    else:
                        bot.send_message(message.chat.id, caption, parse_mode="Markdown")
                    mark_post_seen(user_id, post_url)
                    new_posts_count += 1
                except Exception as e:
                    print(f"Ошибка отправки: {e}")
        try:
            bot.delete_message(message.chat.id, msg.message_id)
        except:
            pass
        if new_posts_count == 0:
            bot.send_message(message.chat.id, "✅ Новых постов нет.", reply_markup=get_main_keyboard())
        else:
            bot.send_message(
                message.chat.id,
                f"📰 Показано новых постов: *{new_posts_count}*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        return

    if text == "📋 Мои каналы":
        channels = get_user_subscriptions(message.from_user.id)
        if not channels:
            bot.send_message(
                message.chat.id,
                "📭 У тебя пока нет добавленных каналов.\n\nНажми *➕ Добавить канал* и скинь ссылку.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return
        msg_text = f"📋 *Твои каналы ({len(channels)}):*\n\n"
        for i, ch in enumerate(channels, 1):
            msg_text += f"{i}. 📢 *{ch['title']}* (@{ch['name']})\n"
        msg_text += "\n_Нажми на канал ниже, чтобы удалить его._"
        keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
        for ch in channels:
            keyboard.add(
                telebot.types.InlineKeyboardButton(
                    f"🗑 Удалить @{ch['name']}",
                    callback_data=f"del_{ch['name']}"
                )
            )
        bot.send_message(message.chat.id, msg_text, parse_mode="Markdown", reply_markup=keyboard)
        return

    if text == "⭐ Отзыв":
        msg = bot.send_message(
            message.chat.id,
            "✍️ Напиши свой отзыв — я передам его автору.",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, process_feedback)
        return

    if text == "🛠 Тех поддержка":
        bot.send_message(
            message.chat.id,
            f"🛠 *Техническая поддержка*\n\n👉 {SUPPORT_NICK}\n\nОтвечаю в течение 24 часов.",
            parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
        return

    if text == "🤝 Сотрудничество":
        bot.send_message(
            message.chat.id,
            f"🤝 *Сотрудничество*\n\n"
            f"• 📢 Взаимный пиар\n"
            f"• 💼 Реклама в боте\n"
            f"• 🛠 Разработка ботов\n\n"
            f"📩 Связь: {AUTHOR_NICK}",
            parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
        return

    if text == "☕ Поддержи автора":
        bot.send_message(
            message.chat.id,
            f"☕ *Поддержать автора*\n\n"
            f"💳 СБП: `{DONATE_SBP}`\n"
            f"💳 Карта: `{DONATE_CARD}`\n\n"
            f"Спасибо! ❤️",
            parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
        return

    # Если пользователь скинул ссылку — показываем посты
    channel_name = extract_channel_name(text)
    if not channel_name:
        bot.reply_to(
            message,
            "❌ Не могу распознать ссылку.\n\nИспользуй кнопку *➕ Добавить канал*.",
            parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
        return

    msg = bot.reply_to(message, f"🔍 Загружаю посты из `{channel_name}`...", parse_mode="Markdown")
    result = get_channel_posts(channel_name, limit=5)
    if not result:
        bot.edit_message_text(
            f"❌ Канал `{channel_name}` не найден.",
            chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown"
        )
        return
    if not result['posts']:
        bot.edit_message_text(
            f"📭 Канал *{result['title']}* найден, но постов нет.",
            chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown"
        )
        return
    try:
        bot.delete_message(message.chat.id, msg.message_id)
    except:
        pass
    bot.send_message(
        message.chat.id,
        f"📰 *{result['title']}*\n@{channel_name}\n━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown"
    )
    for i, post in enumerate(result['posts'], 1):
        caption = f"*{i}.* "
        if post['text']:
            caption += post['text']
        if post['date']:
            caption += f"\n\n🕐 _{post['date']}_"
        if post['url']:
            caption += f"\n🔗 [Открыть пост]({post['url']})"
        if len(caption) > 1000:
            caption = caption[:1000] + "..."
        try:
            if post['photo']:
                bot.send_photo(message.chat.id, post['photo'], caption=caption, parse_mode="Markdown")
            elif post['video'] or post['round_video']:
                bot.send_video(message.chat.id, post['video'] or post['round_video'], caption=caption, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, caption, parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка отправки: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_"))
def delete_channel_callback(call):
    channel_name = call.data.replace("del_", "")
    user_id = call.from_user.id
    remove_subscription(user_id, channel_name)
    channels = get_user_subscriptions(user_id)
    if not channels:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="📭 У тебя больше нет добавленных каналов.\n\nНажми *➕ Добавить канал*, чтобы добавить новый.",
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id, f"Канал @{channel_name} удалён")
        return
    msg_text = f"📋 *Твои каналы ({len(channels)}):*\n\n"
    for i, ch in enumerate(channels, 1):
        msg_text += f"{i}. 📢 *{ch['title']}* (@{ch['name']})\n"
    msg_text += "\n_Нажми на канал ниже, чтобы удалить его._"
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        keyboard.add(
            telebot.types.InlineKeyboardButton(
                f"🗑 Удалить @{ch['name']}",
                callback_data=f"del_{ch['name']}"
            )
        )
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=msg_text,
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id, f"✅ Канал @{channel_name} удалён")

# ===== ВЕБХУК =====

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_string = request.get_data().decode('utf-8')
        if not json_string:
            return "Empty request", 400
        
        # ЛОГИРОВАНИЕ: что пришло от Telegram
        print(f"📥 Webhook получен: {json_string[:500]}")
        
        update_dict = json.loads(json_string)
        update = telebot.types.Update.de_json(update_dict)
        
        # ЛОГИРОВАНИЕ: какой тип сообщения
        print(f"🔍 Update type: {type(update).__name__}, message={update.message is not None}")
        
        # Обрабатываем
        bot.process_new_updates([update])
        
        # ЛОГИРОВАНИЕ: успешная обработка
        print(f"✅ Update обработан успешно")
        
        return "OK", 200
    except Exception as e:
        # ЛОГИРОВАНИЕ ошибки
        import traceback
        print(f"❌ WEBHOOK ERROR: {e}")
        print(f"📜 Traceback:\n{traceback.format_exc()}")
        return f"Error: {e}", 500

# ===== АВТОУСТАНОВКА ВЕБХУКА =====
webhook_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://njktapebot.onrender.com')
full_webhook_url = f"{webhook_url}/webhook"
try:
    bot.remove_webhook()
    bot.set_webhook(url=full_webhook_url)
    print(f"✅ Webhook установлен: {full_webhook_url}")
except Exception as e:
    print(f"⚠️ Ошибка установки вебхука: {e}")

# ===== ЗАПУСК =====
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    print(f"🚀 Сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)
