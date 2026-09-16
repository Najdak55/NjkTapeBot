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

def get_channel_posts(channel_name, limit=5):
    """Возвращает список постов с медиа"""
    try:
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
        
        # Все посты
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
    """Парсит один пост: текст, медиа, дата, ссылка"""
    try:
        # Текст поста
        text_el = post.find('div', class_='tgme_widget_message_text')
        text = text_el.get_text(separator='\n', strip=True) if text_el else ""
        
        # Дата
        time_el = post.find('time')
        date = time_el.get('datetime', '') if time_el else ""
        date_str = ""
        if date:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
            except:
                date_str = date[:16]
        
        # Ссылка на пост
        link_el = post.find('a', class_='tgme_widget_message_date')
        post_url = link_el.get('href', '') if link_el else ""
        
        # Медиа: фото
        photo_url = None
        photo_el = post.find('a', class_='tgme_widget_message_photo_wrap')
        if photo_el:
            style = photo_el.get('style', '')
            # Извлекаем URL из style="background-image:url('...')"
            if 'url(' in style:
                start = style.find("url('") + 5
                end = style.find("')", start)
                if start > 4 and end > start:
                    photo_url = style[start:end]
        
        # Медиа: видео
        video_url = None
        video_el = post.find('video')
        if video_el:
            video_url = video_el.get('src')
        
        # Медиа: кружок
        round_video = None
        round_el = post.find('a', class_='tgme_widget_message_roundvideo_wrap')
        if round_el:
            round_video = round_el.find('video')
            if round_video:
                round_video = round_video.get('src')
        
        # Если нет ни текста, ни медиа — пропускаем
        if not text and not photo_url and not video_url and not round_video:
            return None
        
        return {
            'text': text[:800],  # обрезаем очень длинные
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
    
    msg = bot.reply_to(message, f"🔍 Загружаю посты из `{channel_name}`...", parse_mode="Markdown")
    
    result = get_channel_posts(channel_name, limit=5)
    
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
            f"📭 Канал *{result['title']}* найден, но постов пока нет.",
            chat_id=message.chat.id,
            message_id=msg.message_id,
            parse_mode="Markdown"
        )
        return
    
    # Удаляем сообщение "Загружаю..."
    try:
        bot.delete_message(message.chat.id, msg.message_id)
    except:
        pass
    
    # Заголовок
    bot.send_message(
        message.chat.id,
        f"📰 *{result['title']}*\n"
        f"@{channel_name}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Последние {len(result['posts'])} постов:",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    
    # Отправляем каждый пост отдельно
    for i, post in enumerate(result['posts'], 1):
        # Формируем подпись
        caption = f"*{i}.* "
        if post['text']:
            caption += post['text']
        
        if post['date']:
            caption += f"\n\n🕐 _{post['date']}_"
        
        if post['url']:
            caption += f"\n🔗 [Открыть пост]({post['url']})"
        
        # Обрезаем подпись до лимита Telegram (1024 символа для медиа)
        if len(caption) > 1000:
            caption = caption[:1000] + "..."
        
        try:
            # Отправляем по типу медиа
            if post['photo']:
                bot.send_photo(
                    message.chat.id,
                    post['photo'],
                    caption=caption,
                    parse_mode="Markdown"
                )
            elif post['round_video']:
                # Кружок — отправляем как видео
                bot.send_video(
                    message.chat.id,
                    post['round_video'],
                    caption=caption,
                    parse_mode="Markdown"
                )
            elif post['video']:
                bot.send_video(
                    message.chat.id,
                    post['video'],
                    caption=caption,
                    parse_mode="Markdown"
                )
            else:
                # Только текст
                bot.send_message(
                    message.chat.id,
                    caption,
                    parse_mode="Markdown",
                    disable_web_page_preview=False
                )
        except Exception as e:
            # Если Markdown сломался — отправляем без форматирования
            print(f"Ошибка отправки поста {i}: {e}")
            try:
                if post['photo']:
                    bot.send_photo(message.chat.id, post['photo'], caption=caption.replace('*', '').replace('_', ''))
                else:
                    bot.send_message(message.chat.id, caption.replace('*', '').replace('_', ''))
            except:
                pass
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
