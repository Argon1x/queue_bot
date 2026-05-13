from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from data import get_queues
from permissions import is_admin


def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Список очередей", callback_data="show_queues")],
        [InlineKeyboardButton("➕ Создать очередь", callback_data="create_queue")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def queues_keyboard():
    queues = get_queues()
    keyboard = []
    for qid, title in queues:
        keyboard.append([
            InlineKeyboardButton(f"📌 {title}", callback_data=f"q:open:{qid}")
        ])
    if queues:
        keyboard.append([])
    keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)


def queue_actions_keyboard(queue_id: int, user_id: int):
    keyboard = [
        [InlineKeyboardButton("✍️ Записаться", callback_data=f"q:join:{queue_id}")],
        [InlineKeyboardButton("👁 Посмотреть", callback_data=f"q:view:{queue_id}")],
    ]

    if is_admin(user_id):
        keyboard.append([
            InlineKeyboardButton("➡️ Прошёл", callback_data=f"q:done:{queue_id}"),
            InlineKeyboardButton("⏰ Не успел", callback_data=f"q:fail:{queue_id}"),
        ])
        keyboard.append([
            InlineKeyboardButton("🚫 Неявка", callback_data=f"q:missed:{queue_id}"),
            InlineKeyboardButton("📊 Статистика", callback_data=f"q:stats:{queue_id}"),
        ])
        keyboard.append([InlineKeyboardButton("✅ Прошедшие", callback_data=f"q:passed:{queue_id}")])
        keyboard.append([
            InlineKeyboardButton("🔄 Очистить", callback_data=f"q:clear:{queue_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"q:delete:{queue_id}"),
        ])
    else:
        keyboard.append([InlineKeyboardButton("✅ Прошедшие", callback_data=f"q:passed:{queue_id}")])
        keyboard.append([
            InlineKeyboardButton("👤 Моя позиция", callback_data=f"q:my:{queue_id}"),
            InlineKeyboardButton("❌ Убрать меня", callback_data=f"q:leave:{queue_id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 К списку", callback_data="show_queues")])
    return InlineKeyboardMarkup(keyboard)


def back_to_queue_keyboard(queue_id: int):
    keyboard = [
        [InlineKeyboardButton("🔙 К очереди", callback_data=f"q:open:{queue_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def confirm_keyboard(queue_id: int, action: str, member_id: int = 0):
    if member_id:
        cb_yes = f"confirm:{action}:{queue_id}:{member_id}"
    else:
        cb_yes = f"confirm:{action}:{queue_id}"
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, уверен", callback_data=cb_yes),
            InlineKeyboardButton("❌ Отмена", callback_data=f"q:open:{queue_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def help_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Список очередей", callback_data="show_queues")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(keyboard)
