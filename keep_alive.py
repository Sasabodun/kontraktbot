"""
Модуль для поддержания бота в активном состоянии в Replit
Создает простой веб-сервер для пингования
"""

from flask import Flask
from threading import Thread
import time
import os

app = Flask('')

@app.route('/')
def home():
    return """
    <html>
    <head>
        <title>Discord Contract Bot 3.0 - Status</title>
        <meta charset="utf-8">
    </head>
    <body style="font-family: Arial; background: #2c2f33; color: #ffffff; text-align: center; padding: 50px;">
        <h1>🤖 Discord Contract Bot 3.0</h1>
        <h2 style="color: #7289da;">✅ Бот активен и работает!</h2>
        <p>Время работы: <span id="time"></span></p>
        <p>Статус: <span style="color: #43b581;">🟢 Онлайн</span></p>
        <hr style="border-color: #7289da;">
        <p>Для поддержания активности используйте UptimeRobot</p>
        <p>Пингуйте этот URL каждые 5 минут</p>
        
        <script>
            function updateTime() {
                const now = new Date();
                document.getElementById('time').textContent = now.toLocaleString('ru-RU');
            }
            updateTime();
            setInterval(updateTime, 1000);
        </script>
    </body>
    </html>
    """

@app.route('/ping')
def ping():
    return {'status': 'alive', 'timestamp': time.time(), 'message': 'Bot is running!'}

@app.route('/health')
def health():
    return {'status': 'healthy', 'uptime': time.time()}

def run():
    """Запуск веб-сервера в отдельном потоке"""
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

def keep_alive():
    """Функция для поддержания активности бота"""
    print("🌐 Запуск веб-сервера для поддержания активности...")
    t = Thread(target=run)
    t.daemon = True
    t.start()
    print(f"✅ Веб-сервер запущен! Пингуйте URL вашего Replit каждые 5 минут")
    print("💡 Используйте UptimeRobot для автоматического пингования")
