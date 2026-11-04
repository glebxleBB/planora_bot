import datetime
import logging

from telebot import types

from db import (
    get_approved_barbershops,
    get_barbershop,
    get_services,
    get_service,
    get_barbershop_telegram_id,
    get_working_hours,
    create_appointment,
)
from utils import CITIES, MENU_TEXTS, get_text, today


logger = logging.getLogger(__name__)

# Максимум дней вперёд, на которые можно записаться
MAX_DAYS_AHEAD = 60

# Кнопки клиентской клавиатуры: если нажаты, пока бот ждёт дату,
# это не дата, а переход по меню
CITY_BUTTON = f"{CITIES[0]}🏙"
CLIENT_MENU_TEXTS = MENU_TEXTS | {CITY_BUTTON, "Парикмахерская"}


def parse_date(text):
    """'28.09.2026' -> date; None при ошибке."""
    try:
        day, month, year = map(int, text.split("."))
        return datetime.date(year, month, day)
    except ValueError:
        return None


def check_date(barbershop_id, selected_date):
    """
    Возвращает (текст ошибки, None) или (None, (start, end)) с часами работы.
    """
    current = today()

    if selected_date < current:
        return "❌ Эта дата уже прошла.", None

    if selected_date > current + datetime.timedelta(days=MAX_DAYS_AHEAD):
        return f"❌ Записаться можно максимум на {MAX_DAYS_AHEAD} дней вперёд.", None

    hours = get_working_hours(barbershop_id, selected_date.isoweekday())

    if hours is None:
        return "❌ В этот день парикмахерская не работает.", None

    return None, hours


def register_c(bot):

    @bot.message_handler(func=lambda message: message.text == "👤 Клиент")
    def client(message):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton(CITY_BUTTON))

        bot.send_message(
            message.chat.id,
            "📍 Выберите ваш город:",
            reply_markup=markup)

    @bot.message_handler(func=lambda message: message.text == CITY_BUTTON)
    def city_selected(message):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("Парикмахерская"))

        bot.send_message(
            message.chat.id,
            "Выберите категорию:",
            reply_markup=markup)

    @bot.message_handler(func=lambda message: message.text == "Парикмахерская")
    def barbershops_list(message):
        barbershops = get_approved_barbershops(CITIES[0])

        if not barbershops:
            bot.send_message(
                message.chat.id,
                "😔 Пока нет доступных парикмахерских.")
            return

        markup = types.InlineKeyboardMarkup()

        for barbershop_id, name in barbershops:
            markup.add(types.InlineKeyboardButton(
                name,
                callback_data=f"barbershop_{barbershop_id}"))

        bot.send_message(
            message.chat.id,
            "💇 Выберите парикмахерскую:",
            reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("barbershop_"))
    def select_barbershop(call):
        try:
            barbershop_id = int(call.data.split("_")[1])
        except (IndexError, ValueError):
            bot.answer_callback_query(call.id)
            return

        barbershop = get_barbershop(barbershop_id)

        if barbershop is None:
            bot.answer_callback_query(
                call.id, "Эта парикмахерская больше недоступна.", show_alert=True)
            return

        bot.answer_callback_query(call.id)

        _, name, city, address, phone = barbershop
        services = get_services(barbershop_id)

        if not services:
            bot.send_message(
                call.message.chat.id,
                f"💇 {name}\n\nУ этой парикмахерской пока нет услуг.")
            return

        text = (
            f"💇 {name}\n\n"
            f"📍 Город: {city}\n"
            f"🏠 Адрес: {address}\n"
            f"📞 Телефон: {phone}\n\n"
            f"💰 Услуги:\n"
        )

        markup = types.InlineKeyboardMarkup()

        for service_id, service_name, price in services:
            markup.add(types.InlineKeyboardButton(
                f"{service_name} — {price} ₸",
                callback_data=f"service_{service_id}"))

        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("service_"))
    def select_service(call):
        try:
            service_id = int(call.data.split("_")[1])
        except (IndexError, ValueError):
            bot.answer_callback_query(call.id)
            return

        service = get_service(service_id)

        if service is None:
            bot.answer_callback_query(
                call.id, "Эта услуга больше недоступна.", show_alert=True)
            return

        bot.answer_callback_query(call.id)

        _, _, name, price = service

        bot.send_message(
            call.message.chat.id,
            f"💇 Услуга: {name}\n"
            f"💰 Цена: {price} ₸\n\n"
            f"📅 Введите дату записи в формате ДД.ММ.ГГГГ:\n\n"
            f"Например: 28.09.2026")

        # Сбрасываем прошлое ожидание, чтобы обработчики не копились,
        # если клиент нажал сразу несколько услуг
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
        bot.register_next_step_handler_by_chat_id(
            call.message.chat.id,
            select_date,
            service_id)

    def select_date(message, service_id):
        text = get_text(bot, message, select_date, service_id,
                        interrupts=CLIENT_MENU_TEXTS)
        if text is None:
            return

        service = get_service(service_id)

        if service is None:
            bot.send_message(
                message.chat.id,
                "⚠️ Эта услуга больше недоступна. Начните заново: /start")
            return

        _, barbershop_id, name, price = service

        selected_date = parse_date(text)

        if selected_date is None:
            msg = bot.send_message(
                message.chat.id,
                "❌ Неверный формат даты.\n"
                "Используйте ДД.ММ.ГГГГ\n\n"
                "Например: 28.09.2026")
            bot.register_next_step_handler(msg, select_date, service_id)
            return

        error, hours = check_date(barbershop_id, selected_date)

        if error:
            msg = bot.send_message(
                message.chat.id,
                f"{error}\nВведите другую дату:")
            bot.register_next_step_handler(msg, select_date, service_id)
            return

        start_time, end_time = hours
        date_text = selected_date.strftime("%d.%m.%Y")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "✅ Подтвердить запись",
            callback_data=f"confirm_{service_id}_{selected_date.isoformat()}"))

        bot.send_message(
            message.chat.id,
            f"📅 Дата: {date_text}\n"
            f"🕐 Часы работы: {start_time}–{end_time}\n"
            f"💇 Услуга: {name}\n"
            f"💰 Цена: {price} ₸\n\n"
            f"Подтвердить запись?",
            reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_"))
    def confirm_service(call):
        def fail(text):
            bot.answer_callback_query(call.id, text, show_alert=True)

        parts = call.data.split("_")

        try:
            service_id = int(parts[1])
            selected_date = datetime.date.fromisoformat(parts[2])
        except (IndexError, ValueError):
            fail("Что-то пошло не так. Начните заново: /start")
            return

        service = get_service(service_id)

        if service is None:
            fail("Эта услуга больше недоступна.")
            return

        _, barbershop_id, name, price = service

        # Данные из кнопки могут быть старыми, поэтому проверяем ещё раз
        error, _hours = check_date(barbershop_id, selected_date)

        if error:
            fail(error.replace("❌ ", ""))
            return

        client_id = call.from_user.id
        client_username = call.from_user.username

        if client_username:
            client_contact = f"@{client_username}"
        else:
            client_contact = f"ID: {client_id}"

        created = create_appointment(
            service_id, client_id, selected_date.isoformat())

        # Убираем кнопку, чтобы нельзя было нажать дважды
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id)
        except Exception:
            logger.debug("Не удалось убрать кнопку подтверждения", exc_info=True)

        if not created:
            fail("Вы уже записаны на эту услугу в этот день.")
            return

        bot.answer_callback_query(call.id)

        date_text = selected_date.strftime("%d.%m.%Y")

        bot.send_message(
            call.message.chat.id,
            f"✅ Запись подтверждена!\n\n"
            f"💇 Услуга: {name}\n"
            f"💰 Цена: {price} ₸\n"
            f"📅 Дата: {date_text}\n\n"
            f"Парикмахерская свяжется с вами для уточнения времени.")

        telegram_id = get_barbershop_telegram_id(barbershop_id)

        if telegram_id:
            try:
                bot.send_message(
                    telegram_id,
                    f"🔔 Новая запись!\n\n"
                    f"💇 Услуга: {name}\n"
                    f"💰 Цена: {price} ₸\n"
                    f"📅 Дата: {date_text}\n"
                    f"👤 Клиент: {client_contact}")
            except Exception:
                # Например, владелец заблокировал бота. Запись уже сохранена.
                logger.exception(
                    "Не удалось уведомить владельца (telegram_id=%s)", telegram_id)
