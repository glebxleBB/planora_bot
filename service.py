import datetime
import logging
import re

from telebot import types

from admin import notify_admin
from db import register_barbershop
from utils import CITIES, DAY_SHORT, get_text


logger = logging.getLogger(__name__)

MAX_NAME = 64
MAX_ADDRESS = 200
MAX_SERVICES = 20
MAX_PRICE = 1_000_000

PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{5,19}$")

ADD_SERVICE = "➕ Добавить ещё услугу"
CONTINUE = "✅ Продолжить"
YES = "✅ Да"
NO = "❌ Нет"


def parse_days(text):
    """'1 2, 3' -> [1, 2, 3]; None при ошибке."""
    try:
        days = [int(d) for d in text.replace(",", " ").split()]
    except ValueError:
        return None

    if not days or not all(1 <= d <= 7 for d in days):
        return None

    return sorted(set(days))


def parse_hours(text):
    """'9:00 - 18:00' -> ('09:00', '18:00'); None при ошибке."""
    text = text.replace("–", "-").replace("—", "-").replace(" ", "")
    parts = text.split("-")

    if len(parts) != 2:
        return None

    try:
        start = datetime.datetime.strptime(parts[0], "%H:%M")
        end = datetime.datetime.strptime(parts[1], "%H:%M")
    except ValueError:
        return None

    if start >= end:
        return None

    return start.strftime("%H:%M"), end.strftime("%H:%M")


def register_s(bot):

    # ---------- Вспомогательные ----------

    def ask(chat_id, text, handler, *args, markup=None):
        msg = bot.send_message(
            chat_id,
            text,
            reply_markup=markup or types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, handler, *args)

    def city_markup():
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for city in CITIES:
            markup.add(types.KeyboardButton(city))
        return markup

    def actions_markup():
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton(ADD_SERVICE),
                   types.KeyboardButton(CONTINUE))
        return markup

    def confirm_markup():
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton(YES), types.KeyboardButton(NO))
        return markup

    # ---------- Вход ----------

    @bot.message_handler(func=lambda message: message.text == "🏢 Сервис")
    def service(message):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("💇 Парикмахерская"))

        bot.send_message(
            message.chat.id,
            "🏢 Выберите ваш сервис:",
            reply_markup=markup)

    @bot.message_handler(func=lambda message: message.text == "💇 Парикмахерская")
    def barbershop(message):
        begin(message.chat.id, message.from_user.id)

    def begin(chat_id, owner_id):
        # Все данные копим здесь и пишем в БД только после подтверждения
        data = {"owner_id": owner_id, "services": []}

        ask(chat_id,
            "Введите название вашей парикмахерской:",
            get_name, data)

    # ---------- Название, город, адрес, телефон ----------

    def get_name(message, data):
        text = get_text(bot, message, get_name, data)
        if text is None:
            return

        if len(text) > MAX_NAME:
            ask(message.chat.id,
                f"❌ Слишком длинное название (максимум {MAX_NAME} символов).\n"
                "Введите ещё раз:",
                get_name, data)
            return

        data["name"] = text

        ask(message.chat.id,
            f"Название: {text}\n\nВыберите город:",
            get_city, data,
            markup=city_markup())

    def get_city(message, data):
        text = get_text(bot, message, get_city, data)
        if text is None:
            return

        if text not in CITIES:
            ask(message.chat.id,
                "❌ Выберите город кнопкой на клавиатуре.",
                get_city, data,
                markup=city_markup())
            return

        data["city"] = text

        ask(message.chat.id,
            f"Город: {text}\n\nВведите адрес вашей парикмахерской:",
            get_address, data)

    def get_address(message, data):
        text = get_text(bot, message, get_address, data)
        if text is None:
            return

        if len(text) > MAX_ADDRESS:
            ask(message.chat.id,
                f"❌ Слишком длинный адрес (максимум {MAX_ADDRESS} символов).\n"
                "Введите ещё раз:",
                get_address, data)
            return

        data["address"] = text

        ask(message.chat.id,
            f"Адрес: {text}\n\nВведите номер телефона:",
            get_phone, data)

    def get_phone(message, data):
        text = get_text(bot, message, get_phone, data)
        if text is None:
            return

        if not PHONE_RE.match(text):
            ask(message.chat.id,
                "❌ Неверный номер телефона.\n"
                "Например: +7 777 123 45 67",
                get_phone, data)
            return

        data["phone"] = text

        ask(message.chat.id,
            "Введите название услуги:",
            get_service_name, data)

    # ---------- Услуги ----------

    def get_service_name(message, data):
        text = get_text(bot, message, get_service_name, data)
        if text is None:
            return

        if len(text) > MAX_NAME:
            ask(message.chat.id,
                f"❌ Слишком длинное название (максимум {MAX_NAME} символов).\n"
                "Введите ещё раз:",
                get_service_name, data)
            return

        ask(message.chat.id,
            "Введите цену этой услуги в тенге:",
            get_price, data, text)

    def get_price(message, data, service_name):
        text = get_text(bot, message, get_price, data, service_name)
        if text is None:
            return

        if not (text.isascii() and text.isdigit()) \
                or not 1 <= int(text) <= MAX_PRICE:
            ask(message.chat.id,
                "❌ Цена должна быть числом от 1 до "
                f"{MAX_PRICE}.\nВведите цену ещё раз:",
                get_price, data, service_name)
            return

        price = int(text)
        data["services"].append((service_name, price))

        ask(message.chat.id,
            f"Услуга: {service_name}\n"
            f"Цена: {price} ₸\n\n"
            "Что хотите сделать?",
            service_action, data,
            markup=actions_markup())

    def service_action(message, data):
        text = get_text(bot, message, service_action, data)
        if text is None:
            return

        if text == ADD_SERVICE:
            if len(data["services"]) >= MAX_SERVICES:
                bot.send_message(
                    message.chat.id,
                    f"Достигнут максимум услуг ({MAX_SERVICES}).")
                ask_days(message.chat.id, data)
                return

            ask(message.chat.id,
                "Введите название следующей услуги:",
                get_service_name, data)

        elif text == CONTINUE:
            ask_days(message.chat.id, data)

        else:
            ask(message.chat.id,
                "❌ Нажмите одну из кнопок на клавиатуре.",
                service_action, data,
                markup=actions_markup())

    # ---------- График работы ----------

    def ask_days(chat_id, data):
        ask(chat_id,
            "🗓 Введите номера рабочих дней через пробел:\n\n"
            "1 — Понедельник\n"
            "2 — Вторник\n"
            "3 — Среда\n"
            "4 — Четверг\n"
            "5 — Пятница\n"
            "6 — Суббота\n"
            "7 — Воскресенье\n\n"
            "Например: 1 2 3 4 5 6",
            get_working_days, data)

    def get_working_days(message, data):
        text = get_text(bot, message, get_working_days, data)
        if text is None:
            return

        days = parse_days(text)

        if days is None:
            ask(message.chat.id,
                "❌ Нужны числа от 1 до 7 через пробел.\n"
                "Например: 1 2 3 4 5 6",
                get_working_days, data)
            return

        data["working_days"] = days

        ask(message.chat.id,
            "🕐 Введите время работы:\n\n"
            "Например: 09:00-18:00",
            get_working_hours, data)

    def get_working_hours(message, data):
        text = get_text(bot, message, get_working_hours, data)
        if text is None:
            return

        hours = parse_hours(text)

        if hours is None:
            ask(message.chat.id,
                "❌ Неверный формат или время начала не раньше конца.\n"
                "Например: 09:00-18:00",
                get_working_hours, data)
            return

        data["start_time"], data["end_time"] = hours

        show_summary(message.chat.id, data)

    # ---------- Проверка и сохранение ----------

    def show_summary(chat_id, data):
        text = "📋 Проверьте данные:\n\n"
        text += f"💇 Парикмахерская: {data['name']}\n"
        text += f"📍 Город: {data['city']}\n"
        text += f"🏠 Адрес: {data['address']}\n"
        text += f"📞 Телефон: {data['phone']}\n\n"

        text += "💰 Услуги:\n"
        for name, price in data["services"]:
            text += f"💇 {name} — {price} ₸\n"

        days = ", ".join(DAY_SHORT[d] for d in data["working_days"])
        text += f"\n🗓 Рабочие дни: {days}\n"
        text += f"🕐 Время: {data['start_time']}–{data['end_time']}\n"
        text += "\nВсё верно?"

        ask(chat_id, text, confirm_registration, data,
            markup=confirm_markup())

    def confirm_registration(message, data):
        text = get_text(bot, message, confirm_registration, data)
        if text is None:
            return

        if text == NO:
            bot.send_message(
                message.chat.id,
                "🔄 Хорошо, давайте заново.",
                reply_markup=types.ReplyKeyboardRemove())
            begin(message.chat.id, data["owner_id"])

        elif text == YES:
            try:
                barbershop_id = register_barbershop(
                    data["name"],
                    data["city"],
                    data["address"],
                    data["phone"],
                    data["owner_id"],
                    data["services"],
                    data["working_days"],
                    data["start_time"],
                    data["end_time"])
            except Exception:
                logger.exception("Не удалось сохранить парикмахерскую")
                bot.send_message(
                    message.chat.id,
                    "⚠️ Не удалось сохранить данные. Попробуйте позже: /start",
                    reply_markup=types.ReplyKeyboardRemove())
                return

            bot.send_message(
                message.chat.id,
                "✅ Регистрация завершена и отправлена на проверку!\n\n"
                "Мы сообщим вам о решении.\n"
                "Главное меню: /start",
                reply_markup=types.ReplyKeyboardRemove())

            notify_admin(bot, barbershop_id)

        else:
            ask(message.chat.id,
                f"❌ Нажмите {YES} или {NO}.",
                confirm_registration, data,
                markup=confirm_markup())
