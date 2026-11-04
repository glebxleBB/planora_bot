import logging

from telebot import types

from db import (
    get_barbershop_for_review,
    get_pending_barbershop_ids,
    set_barbershop_status,
)
from config import ADMIN_ID
from utils import DAY_SHORT


logger = logging.getLogger(__name__)


def build_card(shop):
    """Текст карточки заявки для администратора."""
    text = f"🆕 Заявка #{shop['id']}\n\n"
    text += f"💇 {shop['name']}\n"
    text += f"📍 Город: {shop['city']}\n"
    text += f"🏠 Адрес: {shop['address']}\n"
    text += f"📞 Телефон: {shop['phone']}\n"
    text += f"👤 Владелец (Telegram ID): {shop['telegram_id']}\n\n"

    text += "💰 Услуги:\n"
    for name, price in shop["services"]:
        text += f"• {name} — {price} ₸\n"

    if shop["days"]:
        days = ", ".join(DAY_SHORT[d] for d in shop["days"])
        text += f"\n🗓 {days}\n"
        text += f"🕐 {shop['start_time']}–{shop['end_time']}"

    return text


def review_markup(barbershop_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "✅ Одобрить", callback_data=f"approve_{barbershop_id}"),
        types.InlineKeyboardButton(
            "❌ Отклонить", callback_data=f"reject_{barbershop_id}"))
    return markup


def send_review_card(bot, shop):
    bot.send_message(
        ADMIN_ID,
        build_card(shop),
        reply_markup=review_markup(shop["id"]))


def notify_admin(bot, barbershop_id):
    """Отправляет администратору новую заявку. Ошибки не пробрасывает."""
    if ADMIN_ID is None:
        return

    try:
        shop = get_barbershop_for_review(barbershop_id)
        if shop is not None:
            send_review_card(bot, shop)
    except Exception:
        # Например, админ не запускал бота. Заявка осталась в БД,
        # её можно достать командой /pending.
        logger.exception(
            "Не удалось отправить заявку #%s администратору", barbershop_id)


def register_a(bot):

    @bot.message_handler(commands=["pending"],
                         func=lambda message: message.from_user.id == ADMIN_ID)
    def pending(message):
        ids = get_pending_barbershop_ids()

        if not ids:
            bot.send_message(message.chat.id, "✅ Нет заявок на проверку.")
            return

        for barbershop_id in ids:
            shop = get_barbershop_for_review(barbershop_id)
            if shop is not None:
                send_review_card(bot, shop)

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith(("approve_", "reject_")))
    def review(call):
        # Кнопки видит только админ, но проверяем и на случай подделки данных
        if call.from_user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "Нет доступа.", show_alert=True)
            return

        action, _, raw_id = call.data.partition("_")

        try:
            barbershop_id = int(raw_id)
        except ValueError:
            bot.answer_callback_query(call.id)
            return

        shop = get_barbershop_for_review(barbershop_id)

        if shop is None:
            bot.answer_callback_query(call.id, "Заявка не найдена.", show_alert=True)
            return

        approved = action == "approve"
        new_status = "approved" if approved else "rejected"

        if not set_barbershop_status(barbershop_id, new_status):
            bot.answer_callback_query(
                call.id, "Эта заявка уже обработана.", show_alert=True)
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id, call.message.message_id)
            except Exception:
                logger.debug("Не удалось убрать кнопки", exc_info=True)
            return

        bot.answer_callback_query(
            call.id, "Одобрено ✅" if approved else "Отклонено ❌")

        # Обновляем карточку: убираем кнопки и пишем результат
        verdict = "✅ ОДОБРЕНО" if approved else "❌ ОТКЛОНЕНО"
        try:
            bot.edit_message_text(
                f"{build_card(shop)}\n\n{verdict}",
                call.message.chat.id,
                call.message.message_id)
        except Exception:
            logger.debug("Не удалось обновить карточку", exc_info=True)

        # Сообщаем владельцу
        if shop["telegram_id"]:
            if approved:
                owner_text = (
                    f"🎉 Ваша парикмахерская «{shop['name']}» одобрена!\n"
                    "Теперь клиенты могут её находить и записываться.")
            else:
                owner_text = (
                    f"😔 Заявка на «{shop['name']}» отклонена.\n"
                    "Вы можете зарегистрироваться заново: /start")

            try:
                bot.send_message(shop["telegram_id"], owner_text)
            except Exception:
                logger.exception(
                    "Не удалось уведомить владельца (telegram_id=%s)",
                    shop["telegram_id"])
