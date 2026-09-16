import telebot
from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import json
import os

# ===== ТОКЕН =====
TOKEN = "8749981183:AAGptgxFmfqyJ5VKJVA7Vw9__8ScHpflHew"
# =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ===== ПАРСИНГ КАНАЛА =====

def get_channel_posts(channel_name, limit=3):
    """Получает последние посты из публичного канала через t.me/s/"""
    try:
        # Убираем @ если есть
        channel_name = channel_name.replace('@', '').strip()
        
        url = f"https://t.me/s/{channel_name}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Название канала
        title_el = soup.find('div', class_='tgme_channel_info_header_title')
        title = title_el.get_text(strip=True) if title_el else channel_name
        
        # Посты
        posts = soup.find_all('div', class_='tgme_widget_message_wrap')
        
        if not posts:
            return {'title': title, 'posts': [], 'exists': True}
        
        result_posts = []
        for post in posts[-limit:]:
            text_el = post.find('div', class_='tgme_widget_message_text')
            time_el = post.find('time')
            
            text = text_el.get_text(strip=True) if text_el else ""
            date = time_el.get('datetime', '') if time_el else ""
            
            if text:
                # Обрезаем длинные посты
                if len(text) > 400:
                    text = text[:400] + "..."
                
                # Форматируем дату
                date_str = ""
                if date:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                        date_str = dt.strftime("%d.%m.%Y %H:%M")
                    except:
                        date_str = date[:16]
                
                result_posts.append({'text': text, 'date': date_str})
        
        return {'title': title, 'posts': result_posts, 'exists': True}
    
    except Exception as e:
        print(f"Ошибка парсинга {channel_name}: {e}")
        return None


def extract_channel_name(text):
    """Извлекает имя канала из ссылки или текста"""
    text = text.strip()
    
    # Формат: https://t.me/channelname
    if 't.me/' in text:
        parts = text.split('t.me/')
        if len(parts) > 1:
            name = parts[1].split('/')[0].split('?')[0]
            return name
    
    # Формат: @channelname
    if text.startswith('@'):
        return text[1:].split()[0]
    
    # Формат: channelname (без @)
    if ' ' not in text and len(text) < 50:
        return text
    
    return None


# ===== КОМАНДЫ БОТА =====

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "📰 *Привет! Я бот-агрегатор новостей.*\n\n"
        "Просто скинь мне ссылку на публичный Telegram-канал, "
        "и я покажу последние новости из него.\n\n"
        "📌 *Примеры:*\n"
        "`https://t.me/durov`\n"
        "`@breakingmash`\n"
        "`rbc_news`\n\n"
        "⚡ Работаю с любыми *публичными* каналами.",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=['help'])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "❓ *Как пользоваться:*\n\n"
        "1. Открой любой публичный Telegram-канал\n"
        "2. Скопируй ссылку (например, `https://t.me/durov`)\n"
        "3. Отправь её мне\n"
        "4. Я покажу последние 3 поста\n\n"
        "⚠️ *Важно:* работают только *публичные* каналы. "
        "Приватные и закрытые — недоступны.",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.strip()
    
    # Извлекаем имя канала
    channel_name = extract_channel_name(text)
    
    if not channel_name:
        bot.reply_to(
            message,
            "❌ Не могу распознать ссылку на канал.\n\n"
            "Отправь в формате:\n"
            "`https://t.me/durov`\n"
            "или `@durov`",
            parse_mode="Markdown"
        )
        return
    
    # Показываем, что бот работает
    msg = bot.reply_to(message, f"🔍 Ищу канал `{channel_name}`...", parse_mode="Markdown")
    
    # Парсим канал
    result = get_channel_posts(channel_name, limit=3)
    
    if not result:
        bot.edit_message_text(
            f"❌ Не удалось получить данные о канале `{channel_name}`.\n\n"
            f"Возможные причины:\n"
            f"• Канал приватный или не существует\n"
            f"• Канал не имеет публичной веб-версии\n"
            f"• Временная ошибка",
            chat_id=message.chat.id,
            message_id=msg.message_id,
            parse_mode="Markdown"
        )
        return
    
    if not result['posts']:
        bot.edit_message_text(
            f"📭 Канал *{result['title']}* найден, но постов пока нет.\n\n"
            f"Возможно, канал только что создан или закрыт для чтения.",
            chat_id=message.chat.id,
            message_id=msg.message_id,
            parse_mode="Markdown"
        )
        return
    
    # Формируем ответ
    response = f"📰 *{result['title']}*\n"
    response += f"@{channel_name}\n"
    response += "━━━━━━━━━━━━━━━━━━\n\n"
    
    for i, post in enumerate(result['posts'], 1):
        response += f"*{i}.* {post['text']}\n"
        if post['date']:
            response += f"🕐 _{post['date']}_\n"
        response += "\n"
    
    response += "━━━━━━━━━━━━━━━━━━\n"
    response += f"📊 Показано {len(result['posts'])} постов"
    
    # Обрезаем если очень длинно (лимит Telegram 4096)
    if len(response) > 4000:
        response = response[:4000] + "..."
    
    try:
        bot.edit_message_text(
            response,
            chat_id=message.chat.id,
            message_id=msg.message_id,
            parse_mode="Markdown"
        )
    except Exception as e:
        # Если Markdown сломался — отправляем без форматирования
        bot.edit_message_text(
            response.replace('*', '').replace('_', '').replace('`', ''),
            chat_id=message.chat.id,
            message_id=msg.message_id
        )


# ===== ВЕБХУК =====

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_string = request.get_data().decode('utf-8')
        if not json_string:
            return "Empty request", 400
        
        update_dict = json.loads(json_string)
        update = telebot.types.Update.de_json(update_dict)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return f"Error: {e}", 500


@app.route('/')
def index():
    return "News Aggregator Bot is running! 🚀", 200


# ===== ПЕРЕМЕННАЯ ДЛЯ RENDER =====
application = app


# ===== НАСТРОЙКА ВЕБХУКА =====
if __name__ == "__main__":
    # Получаем URL из переменной окружения (Render)
    webhook_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://finance-bot-d268.onrender.com')
    full_webhook_url = f"{webhook_url}/webhook"
    
    try:
        bot.remove_webhook()
        bot.set_webhook(url=full_webhook_url)
        print(f"✅ Webhook установлен: {full_webhook_url}")
    except Exception as e:
        print(f"⚠️ Ошибка установки вебхука: {e}")
    
    # Запускаем Flask-сервер на порту, который требует Render
    port = int(os.environ.get('PORT', 10000))
    print(f"🚀 Сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)
