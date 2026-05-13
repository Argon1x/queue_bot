import logging
import html
import asyncio
import traceback

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

from config import TOKEN
from permissions import is_admin
from data import (
    init_db,
    get_queues,
    get_queue,
    create_queue,
    delete_queue,
    join_queue,
    leave_queue,
    mark_done,
    mark_failed,
    mark_missed,
    return_to_queue,
    remove_member,
    get_active_members,
    get_my_membership,
    get_member_by_id,
    admin_clear_queue,
)
from keyboards import (
    main_menu_keyboard,
    queues_keyboard,
    queue_actions_keyboard,
    back_to_queue_keyboard,
    confirm_keyboard,
)
from helpers import fmt_queue, fmt_passed, fmt_stats, fmt_my_position

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

WAITING_NAME = 1
WAITING_QUEUE_NAME = 2


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Exception while handling an update:", exc_info=context.error)
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logging.error(f"Traceback: {tb}")
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Что-то пошло не так. Попробуй открыть меню заново через /start.",
        )


HELP_TEXT = (
    "<b>📋 Queue Bot — помощь</b>\n\n"
    "Бот для управления очередями. Записывайся, смотри "
    "позицию, отмечай прошедших.\n\n"
    "<b>Команды:</b>\n"
    "/start — открыть меню\n"
    "/help — эта справка\n"
    "/cancel — отменить текущее действие\n\n"
    "<b>Как это работает:</b>\n"
    "1. Открой список очередей\n"
    "2. Выбери нужную\n"
    "3. Запишись или посмотри кто следующий\n\n"
    "<b>Для админов:</b>\n"
    "• отмечать прошедших / не успевших\n"
    "• отмечать неявки\n"
    "• смотреть статистику\n"
    "• очищать и удалять очереди\n"
    "• /miss &lt;id&gt; — отметить неявку по ID"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Привет!</b> Я бот для управления очередями.\n\n"
        "📌 Смотри кто стоит, записывайся, отмечай прошедших.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "back_main":
        await query.edit_message_text(
            "Выбери действие:",
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "show_queues":
        queues = await get_queues()
        if not queues:
            await query.edit_message_text(
                "Очередей пока нет. Создай первую!",
                reply_markup=main_menu_keyboard(),
            )
            return
        await query.edit_message_text(
            "📋 Выбери очередь:",
            reply_markup=queues_keyboard(),
        )
        return

    if data == "help":
        await query.edit_message_text(
            HELP_TEXT,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "create_queue":
        context.user_data["action"] = "create"
        await query.edit_message_text("Введи название новой очереди:")
        return WAITING_QUEUE_NAME

    if data.startswith("confirm:"):
        parts = data.split(":")
        action = parts[1]
        qid = int(parts[2])
        mid = int(parts[3]) if len(parts) > 3 else 0
        return await handle_confirm(query, action, qid, mid, user_id)

    if data.startswith("q:"):
        parts = data.split(":")
        cmd = parts[1]
        qid = int(parts[2])
        return await handle_queue_action(query, context, cmd, qid, user_id)

    if data.startswith("m:"):
        parts = data.split(":")
        cmd = parts[1]
        mid = int(parts[2])
        return await handle_member_action(query, context, cmd, mid, user_id)

    await query.edit_message_text(
        "⚠️ Кнопка устарела. Открой меню заново через /start.",
        reply_markup=main_menu_keyboard(),
    )


async def handle_queue_action(query, context, cmd, qid, user_id):
    q = await get_queue(qid)
    if not q or not q["is_active"]:
        await query.edit_message_text(
            "⚠️ Очередь не найдена или удалена.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if cmd == "open":
        title = html.escape(q["title"])
        await query.edit_message_text(
            f"<b>📌 {title}</b>\n\nЧто хочешь сделать?",
            parse_mode="HTML",
            reply_markup=queue_actions_keyboard(qid, user_id),
        )

    elif cmd == "view":
        text = await fmt_queue(q)
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=back_to_queue_keyboard(qid),
        )

    elif cmd == "passed":
        text = await fmt_passed(q)
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=back_to_queue_keyboard(qid),
        )

    elif cmd == "join":
        context.user_data["join_queue"] = qid
        context.user_data["action"] = "join"
        name_hint = html.escape(query.from_user.first_name or "Имя")
        await query.edit_message_text(
            f"✍️ Введи своё <b>Имя</b> для записи в <b>{html.escape(q['title'])}</b>:\n\n"
            f"Или отправь: <code>{name_hint}</code>",
            parse_mode="HTML",
        )
        return WAITING_NAME

    elif cmd == "my":
        member = await get_my_membership(qid, user_id)
        if not member:
            await query.edit_message_text(
                "❌ Ты не записан в эту очередь.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        else:
            text = await fmt_my_position(q, member)
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )

    elif cmd == "leave":
        ok = await leave_queue(qid, user_id)
        if ok:
            await query.edit_message_text(
                "✅ Ты удалён из очереди.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        else:
            await query.edit_message_text(
                "❌ Ты не был в этой очереди.",
                reply_markup=back_to_queue_keyboard(qid),
            )

    elif cmd == "done":
        if not is_admin(user_id):
            return await query.edit_message_text(
                "⛔ У тебя нет прав для этого действия.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        person = await mark_done(qid, user_id)
        if person is None:
            await query.edit_message_text(
                "❗ Очередь пуста — некого отмечать.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        else:
            name = html.escape(person["display_name"])
            text = f"✅ <b>{name}</b> отмечен как прошедший!\n\n"
            text += await fmt_queue(q)
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )

    elif cmd == "fail":
        if not is_admin(user_id):
            return await query.edit_message_text(
                "⛔ У тебя нет прав для этого действия.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        person = await mark_failed(qid, user_id)
        if person is None:
            await query.edit_message_text(
                "❗ Очередь пуста.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        else:
            name = html.escape(person["display_name"])
            text = f"⏰ <b>{name}</b> не успел!\n\n"
            text += await fmt_queue(q)
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )

    elif cmd == "missed":
        if not is_admin(user_id):
            return await query.edit_message_text(
                "⛔ У тебя нет прав для этого действия.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        members = await get_active_members(qid)
        if not members:
            await query.edit_message_text(
                "❗ Очередь пуста.",
                reply_markup=back_to_queue_keyboard(qid),
            )
            return
        lines = ["<b>Выбери кого отметить:</b>\n"]
        for m in members:
            name = html.escape(m["display_name"])
            lines.append(f"• {name} — /miss_{m['id']}")
        lines.append("\n<i>Нажми на ID чтобы отметить</i>")
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=back_to_queue_keyboard(qid),
        )

    elif cmd == "stats":
        if not is_admin(user_id):
            return await query.edit_message_text(
                "⛔ У тебя нет прав для этого действия.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        text = await fmt_stats(q)
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=back_to_queue_keyboard(qid),
        )

    elif cmd == "clear":
        if not is_admin(user_id):
            return await query.edit_message_text(
                "⛔ У тебя нет прав для этого действия.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        await query.edit_message_text(
            f"⚠️ Ты точно хочешь очистить очередь <b>{html.escape(q['title'])}</b>?\n"
            "Все активные будут удалены.",
            parse_mode="HTML",
            reply_markup=confirm_keyboard(qid, "clear"),
        )

    elif cmd == "delete":
        if not is_admin(user_id):
            return await query.edit_message_text(
                "⛔ У тебя нет прав для этого действия.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        await query.edit_message_text(
            f"⚠️ Ты точно хочешь удалить очередь <b>{html.escape(q['title'])}</b>?",
            parse_mode="HTML",
            reply_markup=confirm_keyboard(qid, "delete"),
        )


async def handle_member_action(query, context, cmd, mid, user_id):
    if not is_admin(user_id):
        await query.edit_message_text(
            "⛔ У тебя нет прав для этого действия.",
            reply_markup=main_menu_keyboard(),
        )
        return

    member = await get_member_by_id(mid)
    if not member:
        await query.edit_message_text(
            "⚠️ Участник не найден.",
            reply_markup=main_menu_keyboard(),
        )
        return

    q = await get_queue(member["queue_id"])
    name = html.escape(member["display_name"])

    if cmd == "missed":
        await mark_missed(mid, user_id)
        text = f"🚫 <b>{name}</b> отмечен как не явившийся.\n\n" + await fmt_queue(q)
    elif cmd == "return":
        result = await return_to_queue(mid, user_id)
        if not result:
            text = "⚠️ Участник уже активен."
        else:
            text = f"↩️ <b>{name}</b> возвращён в очередь.\n\n" + await fmt_queue(q)
    elif cmd == "remove":
        await remove_member(mid, user_id)
        text = f"🗑 <b>{name}</b> удалён.\n\n" + await fmt_queue(q)
    else:
        text = "⚠️ Неизвестное действие."

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=back_to_queue_keyboard(member["queue_id"]),
    )


async def handle_confirm(query, action, qid, mid, user_id):
    if not is_admin(user_id):
        await query.edit_message_text(
            "⛔ У тебя нет прав для этого действия.",
            reply_markup=main_menu_keyboard(),
        )
        return

    q = await get_queue(qid)
    if not q:
        await query.edit_message_text("⚠️ Очередь не найдена.")
        return

    if action == "clear":
        await admin_clear_queue(qid, user_id)
        text = f"🔄 Очередь <b>{html.escape(q['title'])}</b> очищена."
    elif action == "delete":
        await delete_queue(qid, user_id)
        text = f"🗑 Очередь <b>{html.escape(q['title'])}</b> удалена."
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
        return
    else:
        text = "⚠️ Неизвестное действие."

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=back_to_queue_keyboard(qid),
    )


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("action")
    text = update.message.text.strip()
    user = update.effective_user

    if action == "join":
        qid = context.user_data.get("join_queue")
        q = await get_queue(qid)
        if not q:
            await update.message.reply_text(
                "⚠️ Очередь не найдена.",
                reply_markup=main_menu_keyboard(),
            )
            context.user_data.clear()
            return ConversationHandler.END

        result = await join_queue(
            qid,
            user.id,
            user.username or "",
            text,
        )

        if result == "already":
            name = html.escape(text)
            qtitle = html.escape(q["title"])
            await update.message.reply_text(
                f"⚠️ {name} уже стоит в очереди <b>{qtitle}</b>!",
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )
        elif result == "not_found":
            qtitle = html.escape(q["title"])
            await update.message.reply_text(
                f"⚠️ Очередь <b>{qtitle}</b> не найдена.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
        else:
            name = html.escape(text)
            qtitle = html.escape(q["title"])
            queue_text = await fmt_queue(q)
            await update.message.reply_text(
                f"✅ <b>{name}</b> записан на позицию <b>{result}</b> в очереди "
                f"<b>{qtitle}</b>!\n\n{queue_text}",
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )

        context.user_data.clear()
        return ConversationHandler.END

    if action == "create":
        qid = await create_queue(text, user.id)
        if qid is None:
            escaped = html.escape(text)
            await update.message.reply_text(
                f"⚠️ Очередь <b>{escaped}</b> уже существует.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
        else:
            escaped = html.escape(text)
            await update.message.reply_text(
                f"🎉 Очередь <b>{escaped}</b> создана!",
                parse_mode="HTML",
                reply_markup=queue_actions_keyboard(qid, user.id),
            )

        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(
        "Используй /start чтобы открыть меню.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Отменено. Возвращаю в главное меню.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def miss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Нет прав.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /miss <member_id>")
        return

    try:
        mid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    member = await get_member_by_id(mid)
    if not member:
        await update.message.reply_text("⚠️ Участник не найден.")
        return

    await mark_missed(mid, user_id)
    q = await get_queue(member["queue_id"])
    name = html.escape(member["display_name"])
    text = f"🚫 <b>{name}</b> отмечен как не явившийся.\n\n" + await fmt_queue(q)
    await update.message.reply_text(text, parse_mode="HTML")


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_input)
            ],
            WAITING_QUEUE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("miss", miss_command))
    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)

    print("✅ Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
