import discord
import asyncio
from discord.ext import commands, tasks
import time
import logging
import aiohttp
import sys
import random
import string
import os
from discord import app_commands
from datetime import timedelta
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Получаем настройки из переменных окружения
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '5'))
HEARTBEAT_TIMEOUT = float(os.getenv('HEARTBEAT_TIMEOUT', '60.0'))
GUILD_READY_TIMEOUT = float(os.getenv('GUILD_READY_TIMEOUT', '5.0'))

# Настройка логирования с более подробной информацией
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('discord.contract_bot')

intents = discord.Intents.default()
intents.message_content = True

# Настройка бота с параметрами для лучшей стабильности
bot = commands.Bot(
    command_prefix='!', 
    intents=intents,
    heartbeat_timeout=HEARTBEAT_TIMEOUT,  # Конфигурируемый таймаут heartbeat
    guild_ready_timeout=GUILD_READY_TIMEOUT   # Конфигурируемый таймаут готовности гильдии
)

# Хранилище активных контрактов
active_contracts = {}
user_contracts = {}  # Для связи пользователя с его контрактом
completed_contracts = {}  # Для хранения завершенных контрактов

def generate_custom_id():
    """Генерирует уникальный custom_id для кнопок"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

class CleanupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Убираем таймаут полностью
        self.cleanup_button = discord.ui.Button(
            label="🧹 Очистить ЛС", 
            style=discord.ButtonStyle.danger,
            custom_id=f"cleanup_btn_{generate_custom_id()}"
        )
        self.cleanup_button.callback = self.execute_cleanup
        self.add_item(self.cleanup_button)
    
    async def execute_cleanup(self, interaction):
        try:
            # Немедленно отключаем кнопку после нажатия
            self.cleanup_button.disabled = True
            self.cleanup_button.label = "🧹 Очистка..."
            self.cleanup_button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=self)
            
            logger.info(f"Начало очистки ЛС для пользователя {interaction.user.id}")
            
            # Создаем DM-канал
            try:
                user = interaction.user
                if not user.dm_channel:
                    await user.create_dm()
                dm_channel = user.dm_channel
            except discord.Forbidden:
                try:
                    await interaction.followup.send(
                        "❌ Не могу отправить ЛС. Проверьте настройки приватности.",
                        ephemeral=True
                    )
                except:
                    pass
                return
                
            # Получаем ID бота
            bot_user_id = interaction.client.user.id
            messages_to_delete = []
            deletion_errors = 0
            
            # Собираем только свежие сообщения (до 14 дней)
            async for message in dm_channel.history(limit=200):
                if message.author.id == bot_user_id:
                    messages_to_delete.append(message)
            
            # В DM-каналах удаляем сообщения ТОЛЬКО по одному
            deleted_count = 0
            for message in messages_to_delete:
                try:
                    await message.delete()
                    deleted_count += 1
                    # Задержка между удалениями для избежания rate limit
                    await asyncio.sleep(0.5)
                except discord.NotFound:
                    # Сообщение уже удалено
                    pass
                except discord.Forbidden:
                    deletion_errors += 1
                    logger.warning(f"Нет прав для удаления сообщения {message.id}")
                except discord.HTTPException as e:
                    deletion_errors += 1
                    logger.warning(f"Ошибка HTTP при удалении сообщения {message.id}: {e}")
                    # Увеличиваем задержку при ошибках
                    await asyncio.sleep(1.0)
                except Exception as e:
                    deletion_errors += 1
                    logger.error(f"Неожиданная ошибка при удалении сообщения {message.id}: {e}")
            
            # Формируем результат
            result_msg = f"✅ Удалено сообщений: {deleted_count}"
            if deletion_errors > 0:
                result_msg += f"\n⚠️ Возникло ошибок: {deletion_errors}"
            
            # Отправляем результат
            try:
                # Обновляем оригинальное сообщение
                self.cleanup_button.label = "✅ Готово"
                self.cleanup_button.style = discord.ButtonStyle.success
                await interaction.edit_original_response(view=self)
                
                # Отправляем дополнительное уведомление
                await interaction.followup.send(
                    result_msg,
                    ephemeral=True
                )
            except discord.NotFound:
                # Если сообщение уже недоступно, отправляем в ЛС
                try:
                    await dm_channel.send(result_msg)
                except discord.Forbidden:
                    logger.warning(f"Не удалось отправить результат пользователю {user.id}")
        
        except Exception as e:
            logger.error(f"КРИТИЧЕСКАЯ ошибка очистки: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ Произошла критическая ошибка при очистке",
                    ephemeral=True
                )
            except:
                pass

class ContractView(discord.ui.View):
    def __init__(self, bot, contract_id, channel, message):
        super().__init__(timeout=600)  # 10 минут вместо 15
        self.bot = bot
        self.contract_id = contract_id
        self.channel = channel
        self.message = message
        self.start_time = time.time()
        self.reminder_5m = None
        self.reminder_2m = None
        
        # Измененные таймеры для напоминаний
        self.reminder_task_5m = asyncio.create_task(self.send_reminder(300, 5))  # Через 5 мин
        self.reminder_task_2m = asyncio.create_task(self.send_reminder(480, 2))  # Через 8 мин (5+3)
        
    async def send_reminder(self, delay, minutes_left):
        try:
            await asyncio.sleep(delay)
            if self.contract_id not in active_contracts:
                return
                
            reminder_texts = {
                5: "🚨 **СРОЧНО! Запись закрывается через 5 минут!**\n👉 @в организации\n🔥 **Не упусти контракт!**",
                2: "🔥 **ПОСЛЕДНИЕ 2 МИНУТЫ ЗАПИСИ!**\n👉 @в организации\n🚨 **УСПЕЙ ПРИСОЕДИНИТЬСЯ ПРЯМО СЕЙЧАС!**"
            }
            
            msg = await self.channel.send(reminder_texts[minutes_left])
            if minutes_left == 5:
                self.reminder_5m = msg
            else:
                self.reminder_2m = msg
                
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания: {e}")

    async def delete_reminders(self):
        try:
            if self.reminder_5m:
                await self.reminder_5m.delete()
            if self.reminder_2m:
                await self.reminder_2m.delete()
        except discord.NotFound:
            pass
        except Exception as e:
            logger.error(f"Ошибка удаления напоминаний: {e}")

    def cancel_tasks(self):
        if hasattr(self, 'reminder_task_5m') and not self.reminder_task_5m.done():
            self.reminder_task_5m.cancel()
        if hasattr(self, 'reminder_task_2m') and not self.reminder_task_2m.done():
            self.reminder_task_2m.cancel()

    @discord.ui.button(label="✅ Записаться", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join_button(self, interaction, button):
        contract = active_contracts.get(self.contract_id)
        if not contract:
            await interaction.response.send_message("❌ Запись на контракт уже завершена", ephemeral=True)
            return
            
        user_id = interaction.user.id
        if user_id not in contract["participants"]:
            contract["participants"].append(user_id)
            await self.update_message(interaction)
            await interaction.response.send_message("✅ Вы записаны на контракт!", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Вы уже записаны на этот контракт", ephemeral=True)
    
    async def update_message(self, interaction):
        contract = active_contracts[self.contract_id]
        participants = contract["participants"]
        message = contract["message"]
        
        embed = discord.Embed(
            title="📢 Кто хочет подзаработать?",
            description="📝 Идет запись на контракт!\n\n"
                        f"Автор: <@{contract['creator']}>",
            color=0x3498db
        )
        
        if participants:
            participants_list = "\n".join([f"<@{uid}>" for uid in participants])
            embed.add_field(
                name=f"✅ Записалось ({len(participants)}):",
                value=participants_list,
                inline=False
            )
        else:
            embed.add_field(
                name="✅ Участники:",
                value="Пока никто не записался",
                inline=False
            )
        
        # Обновленное время до закрытия (10 минут)
        elapsed_time = time.time() - self.start_time
        time_left = max(0, 600 - elapsed_time)  # 600 сек = 10 минут
        minutes_left = int(time_left // 60)
        seconds_left = int(time_left % 60)
        
        if minutes_left > 0:
            time_display = f"{minutes_left} мин {seconds_left} сек"
        else:
            time_display = f"{seconds_left} сек"
            
        embed.set_footer(text=f"Запись закроется через {time_display}")
        
        try:
            await message.edit(embed=embed, view=self)
        except discord.HTTPException as e:
            logger.error(f"Ошибка обновления сообщения: {e}")
    
    async def on_timeout(self):
        self.cancel_tasks()
        contract = active_contracts.get(self.contract_id)
        if not contract:
            return
            
        message = contract["message"]
        participants = contract["participants"]
        creator_id = contract["creator"]
        
        await self.delete_reminders()
        
        # Формируем список участников для уведомлений
        participants_list = "\n".join([f"<@{uid}>" for uid in participants]) if participants else "❌ Участников нет"
        
        # Обновляем основное сообщение контракта
        try:
            if participants:
                final_content = (
                    f"# 🚀 Контракт начал выполнение!\n"
                    f"**Автор:** <@{creator_id}>\n\n"
                    f"**Состав команды:**\n"
                    f"{participants_list}"
                )
                
                embed = discord.Embed(
                    title="✅ Контракт запущен!",
                    description="Запись завершена, команда приступает к выполнению.",
                    color=0x00ff00
                )
            else:
                final_content = "❌ Контракт отменен - нет участников"
                embed = discord.Embed(
                    title="❌ Контракт отменен",
                    description="Не набрано достаточно участников",
                    color=0xff0000
                )
            
            await message.edit(content=final_content, embed=embed, view=None)
        except discord.HTTPException as e:
            logger.error(f"Ошибка обновления финального сообщения: {e}")
        
        # ===== УВЕДОМЛЕНИЯ =====
        try:
            # Уведомление создателя в ЛС с кнопкой очистки
            creator = await self.bot.fetch_user(creator_id)
            cleanup_view = CleanupView()
            
            await creator.send(
                "⏱️ **Запись на ваш контракт завершена!**\n"
                f"**Состав команды:**\n{participants_list}\n"
                f"Создайте контракт и добавьте людей для выполнения!",
                view=cleanup_view
            )
            
            # Задержка 30 секунд перед отправкой уведомления в канал
            await asyncio.sleep(30)
            
            # Уведомление в канал для остальных
            notification = await self.channel.send(
                "⛔ **Запись на контракт закрыта!**\n"
                "👉 @в организации\n"
                "🔥 Кто не успел — тот опоздал! 😉"
            )
            
            # Автоматическое удаление через 5 минут
            async def delete_notification():
                await asyncio.sleep(300)
                try:
                    await notification.delete()
                except Exception as e:
                    logger.error(f"Ошибка удаления уведомления: {e}")
                    
            asyncio.create_task(delete_notification())
            
        except discord.Forbidden:
            logger.warning(f"Не удалось отправить уведомление создателю {creator_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
        # ===== КОНЕЦ УВЕДОМЛЕНИЙ =====
        
        # Перенос в завершенные контракты
        completed_contracts[self.contract_id] = {
            "message_id": message.id,
            "channel_id": message.channel.id,
            "start_time": time.time()
        }
        
        # Очистка активных данных
        if self.contract_id in active_contracts:
            if creator_id in user_contracts:
                del user_contracts[creator_id]
            del active_contracts[self.contract_id]

# ===== SLASH КОМАНДЫ (ПОЯВЯТСЯ В ИНТЕРФЕЙСЕ DISCORD) =====

@bot.tree.command(name="старт", description="Создать запись на контракт")
@app_commands.guild_only()  # Команда доступна только на серверах
async def start_slash(interaction: discord.Interaction):
    """Slash команда для создания контракта"""
    # Блокировка команды в ЛС
    if isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message(
            "❌ Эта команда недоступна в личных сообщениях",
            ephemeral=True
        )
        return
        
    # Проверяем, есть ли у пользователя активный контракт
    if interaction.user.id in user_contracts:
        await interaction.response.send_message("❌ У вас уже есть активный контракт!", ephemeral=True)
        return
        
    contract_id = f"{interaction.channel.id}-{interaction.id}"
    
    # Создаем view
    view = ContractView(bot, contract_id, interaction.channel, None)
    
    active_contracts[contract_id] = {
        "creator": interaction.user.id,
        "participants": [interaction.user.id],
        "message": None,
        "view": view
    }
    user_contracts[interaction.user.id] = contract_id
    
    embed = discord.Embed(
        title="📢 Кто хочет подзаработать?",
        description="📝 Идет запись на контракт!\n\n"
                    f"Автор: {interaction.user.mention}",
        color=0x3498db
    )
    
    embed.add_field(
        name=f"✅ Записалось (1):",
        value=f"{interaction.user.mention}",
        inline=False
    )
    
    embed.set_footer(text="Запись закроется через 10 минут")
    
    try:
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        
        # Обновляем ссылки
        active_contracts[contract_id]["message"] = msg
        view.message = msg
    except discord.HTTPException as e:
        logger.error(f"Ошибка создания контракта: {e}")
        await interaction.response.send_message("❌ Произошла ошибка при создании контракта", ephemeral=True)

@bot.tree.command(name="очистить", description="Очистить ЛС от сообщений бота")
@app_commands.guild_only()  # Команда доступна только на серверах
async def cleanup_slash(interaction: discord.Interaction):
    """Только для использования на серверах"""
    await interaction.response.send_message(
        "❌ Используйте эту команду в личных сообщениях бота!",
        ephemeral=True
    )

# ===== ОБЫЧНЫЕ КОМАНДЫ (ОСТАВЛЯЕМ ДЛЯ СОВМЕСТИМОСТИ) =====

# Создать контракт
@bot.command(name='с', aliases=['c'])
async def start_contract(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    
    if ctx.author.id in user_contracts:
        msg = await ctx.send("❌ У вас уже есть активный контракт!", delete_after=10)
        return
        
    contract_id = f"{ctx.channel.id}-{ctx.message.id}"
    
    # Создаем view
    view = ContractView(bot, contract_id, ctx.channel, None)
    
    active_contracts[contract_id] = {
        "creator": ctx.author.id,
        "participants": [ctx.author.id],
        "message": None,
        "view": view  # Сохраняем view в контракте
    }
    user_contracts[ctx.author.id] = contract_id
    
    embed = discord.Embed(
        title="📢 Кто хочет подзаработать?",
        description="📝 Идет запись на контракт!\n\n"
                    f"Автор: {ctx.author.mention}",
        color=0x3498db
    )
    embed.add_field(
        name=f"✅ Записалось (1):",
        value=f"{ctx.author.mention}",
        inline=False
    )
    embed.set_footer(text="Запись закроется через 10 минут")
    
    try:
        msg = await ctx.send(embed=embed, view=view)
        
        # Обновляем ссылки
        active_contracts[contract_id]["message"] = msg
        view.message = msg
    except discord.HTTPException as e:
        logger.error(f"Ошибка создания контракта: {e}")
        await ctx.send("❌ Произошла ошибка при создании контракта", delete_after=10)

# Отменить контракт
@bot.command(name='о', aliases=['o'])
async def cancel_contract(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    
    if ctx.author.id not in user_contracts:
        await ctx.send("❌ У вас нет активных контрактов!", delete_after=10)
        return
        
    contract_id = user_contracts[ctx.author.id]
    contract = active_contracts.get(contract_id)
    
    if contract:
        # Используем сохранённый view
        if "view" in contract and contract["view"]:
            view = contract["view"]
            view.cancel_tasks()
            await view.delete_reminders()
        
        try:
            if contract["message"]:
                await contract["message"].delete()
        except:
            pass
        del active_contracts[contract_id]
    
    del user_contracts[ctx.author.id]
    await ctx.send("✅ Запись на контракт отменена!", delete_after=10)

# Завершить запись
@bot.command(name='з', aliases=['z'])
async def close_contract(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    
    if ctx.author.id not in user_contracts:
        await ctx.send("❌ У вас нет активных контрактов!", delete_after=10)
        return
        
    contract_id = user_contracts[ctx.author.id]
    contract = active_contracts.get(contract_id)
    
    if not contract:
        await ctx.send("❌ Контракт не найден!", delete_after=10)
        return
    
    # Используем сохранённый view
    if "view" in contract and contract["view"]:
        view = contract["view"]
        view.timeout = 0
        await view.on_timeout()
    
    del user_contracts[ctx.author.id]
    await ctx.send("✅ Запись на контракт завершена досрочно!", delete_after=10)

# Список контрактов
@bot.command(name='л', aliases=['l'])
async def list_contracts(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    
    if not active_contracts:
        await ctx.send("ℹ️ Активных записей на контракты нет", delete_after=15)
        return
        
    embed = discord.Embed(
        title="📋 Активные записи на контракты",
        color=0x3498db
    )
    
    for contract_id, contract in active_contracts.items():
        try:
            creator = await bot.fetch_user(contract["creator"])
            participants = contract["participants"]
            time_left = "Неизвестно"
            if "view" in contract and contract["view"]:
                elapsed = time.time() - contract["view"].start_time
                remaining = max(0, 600 - elapsed)  # 10 минут
                time_left = f"{int(remaining // 60)} мин"
            
            embed.add_field(
                name=f"Контракт от {creator.display_name}",
                value=f"Участников: {len(participants)}\nОсталось: {time_left}",
                inline=False
            )
        except Exception as e:
            logger.error(f"Ошибка получения информации о контракте {contract_id}: {e}")
    
    await ctx.send(embed=embed)

# Команда для очистки ЛС (можно вызвать командой)
@bot.command(name='очистить', aliases=['clear', 'clean'])
async def cleanup_dm(ctx):
    # Проверяем, что команда вызвана в ЛС
    if not isinstance(ctx.channel, discord.DMChannel):
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send("❌ Эта команда работает только в личных сообщениях!", delete_after=10)
        return
    
    # Отправляем упрощенный интерфейс (только одну кнопку)
    view = CleanupView()
    try:
        msg = await ctx.send(
            "🧹 **Очистка сообщений**\nНажмите кнопку ниже чтобы удалить все мои сообщения",
            view=view
        )
        logger.info(f"Отправлено сообщение очистки для {ctx.author.id}: {msg.id}")
    except discord.Forbidden:
        logger.warning(f"Не удалось отправить сообщение очистки для {ctx.author.id}")

@tasks.loop(minutes=10)
async def clean_old_contracts():
    current_time = time.time()
    to_remove = []
    
    contracts_to_check = list(completed_contracts.items())
    
    for contract_id, contract in contracts_to_check:
        if current_time - contract["start_time"] > 7200:
            try:
                channel = bot.get_channel(contract["channel_id"])
                if channel is None:
                    channel = await bot.fetch_channel(contract["channel_id"])
                message = await channel.fetch_message(contract["message_id"])
                await message.delete()
                logger.info(f"Удалено сообщение контракта {contract_id}")
            except discord.NotFound:
                logger.info(f"Сообщение {contract['message_id']} уже удалено")
            except discord.Forbidden:
                logger.warning(f"Нет прав для удаления сообщения в канале {contract['channel_id']}")
            except Exception as e:
                logger.error(f"Ошибка при удалении контракта {contract_id}: {e}")
            finally:
                to_remove.append(contract_id)
    
    for contract_id in to_remove:
        try:
            del completed_contracts[contract_id]
            logger.info(f"Удалён контракт {contract_id} из хранилища")
        except KeyError:
            pass

# Улучшенная обработка событий
@bot.event
async def on_ready():
    logger.info(f"Бот {bot.user.name} готов! (ID: {bot.user.id})")
    logger.info(f"Подключен к {len(bot.guilds)} серверам")
    
    # Синхронизируем slash команды
    try:
        synced = await bot.tree.sync()
        logger.info(f"Синхронизировано {len(synced)} slash команд")
    except Exception as e:
        logger.error(f"Ошибка синхронизации slash команд: {e}")
    
    # Запускаем задачу очистки старых контрактов
    if not clean_old_contracts.is_running():
        clean_old_contracts.start()

@bot.event
async def on_disconnect():
    logger.warning("Бот отключен от Discord")

@bot.event
async def on_resumed():
    logger.info("Соединение с Discord восстановлено")

# Обработка ошибок подключения
@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Произошла ошибка в событии {event}: {args}", exc_info=True)

# Обработка ошибок команд
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Игнорируем неизвестные команды
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас нет прав для выполнения этой команды", delete_after=10)
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("❌ У бота нет необходимых прав", delete_after=10)
    else:
        logger.error(f"Ошибка команды {ctx.command}: {error}", exc_info=True)
        await ctx.send("❌ Произошла ошибка при выполнении команды", delete_after=10)

# Функция для безопасного завершения работы
async def shutdown():
    logger.info("Начинаем завершение работы бота...")
    
    # Отменяем все активные задачи
    for contract_id, contract in active_contracts.items():
        if "view" in contract and contract["view"]:
            contract["view"].cancel_tasks()
    
    # Останавливаем периодические задачи
    if clean_old_contracts.is_running():
        clean_old_contracts.stop()
    
    # Закрываем соединение с Discord
    await bot.close()
    logger.info("Бот завершил работу")

# Запуск с улучшенной обработкой ошибок
async def main():
    max_retries = MAX_RETRIES
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"Попытка запуска бота... (попытка {retry_count + 1}/{max_retries})")
            
            # Используем aiohttp.ClientTimeout для более точного контроля таймаутов
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=60,
                enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            ) as session:
                # Получаем токен из переменных окружения
                discord_token = os.getenv('DISCORD_TOKEN')
                if not discord_token:
                    logger.error("DISCORD_TOKEN не найден в переменных окружения!")
                    logger.error("Создайте файл .env и добавьте: DISCORD_TOKEN=ваш_токен")
                    return
                
                # Запускаем бота с токеном из переменных окружения
                await bot.start(discord_token)
                
        except (OSError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            retry_count += 1
            wait_time = min(2 ** retry_count, 60)  # Экспоненциальная задержка, максимум 60 сек
            
            logger.error(f"Ошибка подключения: {e}")
            
            if retry_count < max_retries:
                logger.info(f"Попытка переподключения через {wait_time} секунд...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("Достигнуто максимальное количество попыток подключения")
                break
                
        except discord.LoginFailure:
            logger.error("Ошибка авторизации: неверный токен")
            break
            
        except KeyboardInterrupt:
            logger.info("Получен сигнал завершения работы")
            await shutdown()
            break
            
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}", exc_info=True)
            retry_count += 1
            
            if retry_count < max_retries:
                await asyncio.sleep(10)
            else:
                logger.error("Критическая ошибка, завершение работы")
                break

if __name__ == "__main__":
    try:
        # Настройка для Windows для корректной работы с asyncio
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа завершена пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}", exc_info=True)