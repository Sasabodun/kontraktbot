#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа для Discord Contract Bot 3.0 (Replit версия)
"""

import os
import sys

# Проверяем переменные окружения для Replit
def check_environment():
    print("🔍 Проверка окружения...")
    
    # Проверяем токен Discord
    if not os.getenv('DISCORD_TOKEN'):
        print("❌ DISCORD_TOKEN не найден!")
        print("📝 В Replit:")
        print("   1. Перейдите в 'Secrets' (замочек слева)")
        print("   2. Добавьте DISCORD_TOKEN = ваш_токен")
        print("   3. Перезапустите проект")
        return False
    
    print("✅ DISCORD_TOKEN найден")
    return True

def setup_replit():
    """Настройка для работы в Replit"""
    try:
        # Создаем файл .env из секретов Replit
        if os.getenv('DISCORD_TOKEN') and not os.path.exists('.env'):
            with open('.env', 'w') as f:
                f.write(f"DISCORD_TOKEN={os.getenv('DISCORD_TOKEN')}\n")
                f.write("LOG_LEVEL=INFO\n")
            print("✅ Файл .env создан из секретов Replit")
        
        # Устанавливаем зависимости если нужно
        try:
            import discord
            import dotenv
            print("✅ Все зависимости установлены")
        except ImportError as e:
            print(f"⚠️ Нужна установка зависимостей: {e}")
            print("💡 Replit должен автоматически установить их")
            
    except Exception as e:
        print(f"⚠️ Ошибка настройки Replit: {e}")

if __name__ == "__main__":
    print("🚀 Discord Contract Bot 3.0 - Replit Edition")
    print("=" * 50)
    
    # Проверяем окружение
    if not check_environment():
        sys.exit(1)
    
    # Настройка для Replit
    setup_replit()
    
    try:
        print("📦 Импорт модулей...")
        
        # Запускаем веб-сервер для поддержания активности в Replit
        try:
            from keep_alive import keep_alive
            keep_alive()
        except ImportError:
            print("⚠️ Flask не установлен - веб-сервер недоступен")
            print("💡 Для поддержания активности установите: pip install flask")
        
        # Импортируем основной модуль бота
        exec(open('discord_bot.py').read())
        
    except FileNotFoundError:
        print("❌ Файл discord_bot.py не найден!")
        print("📁 Убедитесь, что все файлы загружены в Replit")
        sys.exit(1)
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        print("📦 Установите зависимости в Replit:")
        print("   poetry add discord.py python-dotenv aiohttp")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
