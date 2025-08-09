#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа для Discord Contract Bot 3.0
Импортирует и запускает основной бот
"""

import sys
import os

# Добавляем текущую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        # Импортируем основной модуль бота
        import discord_bot
        print("🤖 Discord Contract Bot 3.0 запускается...")
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        print("Убедитесь, что файл discord_bot.py находится в той же папке")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
