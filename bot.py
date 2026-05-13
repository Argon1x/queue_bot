import logging
import html
import asyncio
import traceback

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

from config import TOKEN, ADMIN_IDS
from permissions import is_admin, is_blocked, is_super_admin, reload_permissions
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
    set_user_profile,
    get_user_profile,
    get_next_member,
    get_all_profiles,
    join_queue_force,
    add_bot_admin,
    remove_bot_admin,
    get_bot_admins,
    block_user,
    unblock_user,
    get_blocked_users,
    move_to_front,
)
from keyboards import (
    main_menu_keyboard,
    queues_keyboard,
    queue_actions_keyboard,
    back_to_queue_keyboard,
    confirm_keyboard,
)
from helpers import fmt_queue, fmt_passed, fmt_stats, fmt_my_position

logger = logging.getLogger(__name__)

ADMIN_CHAT_ID = ADMIN_IDS[0] if ADMIN_IDS else 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

WAITING_NAME = 1
WAITING_QUEUE_NAME = 2
WAITING_ADD_USER_ID = 3
WAITING_ADD_USER_NAME = 4


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
        return
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
    "<b>Команды (работают везде):</b>\n"
    "/start — открыть меню\n"
    "/link <b>Имя</b> — привязать Telegram к имени\n"
    "/help — эта справка\n"
    "/cancel — отменить текущее действие\n\n"
    "<b>Как это работает:</b>\n"
    "1. Отправь /link <b>Имя</b> — бот запомнит тебя\n"
    "2. Открой список очередей через /start\n"
    "3. Выбери нужную и нажми «Записаться»\n\n"
    "<b>Для админов (дополнительно):</b>\n"
    "/users — список привязанных пользователей\n"
    "/miss &lt;id&gt; — отметить неявку по ID\n"
    "а также кнопки в меню очереди"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "👋 <b>Привет!</b> Я бот для управления очередями.\n\n"
        "📌 Смотри кто стоит, записывайся, отмечай прошедших.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user_id),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user_id),
    )


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if not args:
        profile = await get_user_profile(user.id)
        if profile:
            name = html.escape(profile["display_name"])
            await update.message.reply_text(
                f"👤 Ты привязан как <b>{name}</b>\n"
                f"Измени: /link <b>НовоеИмя</b>",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "❌ Ты не привязан.\n"
                "Используй: /link <b>ТвоёИмя</b>\n"
                "Например: /link Иван",
                parse_mode="HTML",
            )
        return

    name = " ".join(args).strip()
    if len(name) > 50:
        await update.message.reply_text("⚠️ Имя слишком длинное (макс. 50 символов).")
        return

    await set_user_profile(user.id, user.username or "", name)
    await update.message.reply_text(
        f"✅ Ты привязан как <b>{html.escape(name)}</b>!\n\n"
        "Теперь можешь записаться в любую очередь одной кнопкой.",
        parse_mode="HTML",
    )
    if ADMIN_CHAT_ID:
        try:
            user_link = f"@{html.escape(user.username)}" if user.username else f"<code>{user.id}</code>"
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"✅ <b>{html.escape(name)}</b> ({user_link}) привязал Telegram.\n"
                     f"ID: <code>{user.id}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Нет прав.")
        return

    profiles = await get_all_profiles()
    if not profiles:
        await update.message.reply_text(
            "📭 Нет привязанных пользователей.\n"
            "Команда /link <b>Имя</b> — привязывает Telegram к имени.",
            parse_mode="HTML",
        )
        return

    lines = ["<b>📋 Привязки Telegram → имя:</b>\n"]
    for p in profiles:
        name = html.escape(p["display_name"])
        uid = p["telegram_user_id"]
        username = html.escape(p["username"]) if p["username"] else "—"
        created = p["created_at"].strftime("%d.%m %H:%M") if p["created_at"] else "?"
        lines.append(f"• <code>{uid}</code> → <b>{name}</b> (@{username}) [{created}]")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if is_blocked(user_id):
        await query.edit_message_text("🚫 Ты заблокирован. Обратись к администратору.")
        return

    if data == "back_main":
        await query.edit_message_text(
            "Выбери действие:",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    if data == "show_queues":
        queues = await get_queues()
        if not queues:
            await query.edit_message_text(
                "Очередей пока нет. Создай первую!",
                reply_markup=main_menu_keyboard(user_id),
            )
            return
        await query.edit_message_text(
            "📋 Выбери очередь:",
            reply_markup=await queues_keyboard(),
        )
        return

    if data == "help":
        await query.edit_message_text(
            HELP_TEXT,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    if data == "show_users":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Нет прав.")
        profiles = await get_all_profiles()
        if not profiles:
            text = "📭 Нет привязанных пользователей."
        else:
            lines = ["<b>📋 Привязки Telegram → имя:</b>\n"]
            for p in profiles:
                name = html.escape(p["display_name"])
                uid = p["telegram_user_id"]
                username = html.escape(p["username"]) if p["username"] else "—"
                created = p["created_at"].strftime("%d.%m %H:%M") if p["created_at"] else "?"
                lines.append(f"• <code>{uid}</code> → <b>{name}</b> (@{username}) [{created}]")
            text = "\n".join(lines)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard(user_id))
        return

    if data == "admin_panel":
        if not is_super_admin(user_id):
            return await query.edit_message_text("⛔ Нет прав.")
        kb = [
            [InlineKeyboardButton("👑 Назначить админа", callback_data="admin:list:makeadmin")],
            [InlineKeyboardButton("👑 Снять админа", callback_data="admin:list:removeadmin")],
            [InlineKeyboardButton("🚫 Заблокировать", callback_data="admin:list:block")],
            [InlineKeyboardButton("🔓 Разблокировать", callback_data="admin:list:unblock")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "⚙️ <b>Управление участниками</b>\n\nВыбери действие:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    if data.startswith("admin:"):
        if not is_super_admin(user_id):
            return await query.edit_message_text("⛔ Нет прав.")
        segs = data.split(":")
        cmd = segs[1]

        if cmd == "list" and len(segs) >= 3:
            sub = segs[2]
            profiles = await get_all_profiles()
            blocked = {r["telegram_user_id"] for r in await get_blocked_users()}
            db_admins = {r["telegram_user_id"] for r in await get_bot_admins()}
            if sub == "block":
                items = [p for p in profiles if p["telegram_user_id"] not in blocked]
                title = "🚫 Выбери кого заблокировать:"
            elif sub == "unblock":
                items = [p for p in profiles if p["telegram_user_id"] in blocked]
                title = "🔓 Выбери кого разблокировать:"
            elif sub == "makeadmin":
                items = [p for p in profiles if p["telegram_user_id"] not in db_admins and p["telegram_user_id"] not in ADMIN_IDS]
                title = "👑 Выбери кого назначить админом:"
            elif sub == "removeadmin":
                items = [p for p in profiles if p["telegram_user_id"] in db_admins]
                title = "👑 Выбери кого снять с админки:"
            else:
                return
            if not items:
                await query.edit_message_text(
                    "📭 Нет подходящих пользователей.",
                    reply_markup=main_menu_keyboard(user_id),
                )
                return
            kb = []
            for p in items:
                name = html.escape(p["display_name"])
                uid = p["telegram_user_id"]
                kb.append([InlineKeyboardButton(
                    f"{name} ({uid})",
                    callback_data=f"admin:do:{sub}:{uid}",
                )])
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
            await query.edit_message_text(
                title,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb),
            )

        elif cmd == "do" and len(segs) >= 4:
            sub = segs[2]
            target_uid = int(segs[3])
            if sub == "makeadmin":
                await add_bot_admin(target_uid, user_id)
                await reload_permissions()
                msg = f"✅ <code>{target_uid}</code> назначен администратором!"
            elif sub == "removeadmin":
                await remove_bot_admin(target_uid)
                await reload_permissions()
                msg = f"✅ <code>{target_uid}</code> снят с админки."
            elif sub == "block":
                await block_user(target_uid, user_id)
                await reload_permissions()
                msg = f"🚫 <code>{target_uid}</code> заблокирован."
            elif sub == "unblock":
                await unblock_user(target_uid)
                await reload_permissions()
                msg = f"🔓 <code>{target_uid}</code> разблокирован."
            else:
                return
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=main_menu_keyboard(user_id))
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
        reply_markup=main_menu_keyboard(user_id),
    )


async def handle_queue_action(query, context, cmd, qid, user_id):
    q = await get_queue(qid)
    if not q or not q["is_active"]:
        await query.edit_message_text(
            "⚠️ Очередь не найдена или удалена.",
            reply_markup=main_menu_keyboard(user_id),
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
        profile = await get_user_profile(user_id)
        if not profile:
            await query.edit_message_text(
                "❌ <b>Сначала привяжи имя!</b>\n\n"
                "Используй /link <b>Имя</b>\n"
                "Например: /link Иван\n\n"
                "После этого сможешь записаться одной кнопкой.",
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )
            return
        name = profile["display_name"]
        result = await join_queue(qid, user_id, query.from_user.username or "", name)
        if result == "already":
            await query.edit_message_text(
                f"⚠️ <b>{html.escape(name)}</b> уже в очереди <b>{html.escape(q['title'])}</b>!",
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )
        elif result == "not_found":
            await query.edit_message_text(
                "⚠️ Очередь не найдена.",
                reply_markup=back_to_queue_keyboard(qid),
            )
        else:
            qtitle = html.escape(q["title"])
            text = (
                f"✅ <b>{html.escape(name)}</b> записан на позицию <b>{result}</b> "
                f"в очередь <b>{qtitle}</b>!\n\n"
                + await fmt_queue(q)
            )
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )
            if ADMIN_CHAT_ID:
                try:
                    uname = query.from_user.username or ""
                    user_link = f"@{html.escape(uname)}" if uname else f"<code>{user_id}</code>"
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"📝 <b>{html.escape(name)}</b> ({user_link}) записался в <b>{qtitle}</b> на позицию {result}.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

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
            next_member = await get_next_member(qid)
            if next_member and next_member["telegram_user_id"]:
                try:
                    await context.bot.send_message(
                        chat_id=next_member["telegram_user_id"],
                        text=f"🎯 <b>Твоя очередь!</b>\n\n"
                             f"Очередь: <b>{html.escape(q['title'])}</b>\n"
                             f"Ты следующий! Подготовься.",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.warning(
                        "Could not notify user %s", next_member["telegram_user_id"]
                    )

    elif cmd == "fail":
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

    elif cmd == "movefront":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Нет прав.")
        members = await get_active_members(qid)
        if not members:
            await query.edit_message_text(
                "❗ Очередь пуста.",
                reply_markup=back_to_queue_keyboard(qid),
            )
            return
        kb = []
        for m in members:
            name = html.escape(m["display_name"])
            kb.append([InlineKeyboardButton(
                f"⬆️ {name}",
                callback_data=f"m:movefront:{m['id']}",
            )])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data=f"q:open:{qid}")])
        await query.edit_message_text(
            "⬆️ <b>Кого переместить в начало?</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    elif cmd == "adduser":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Нет прав.")
        context.user_data["action"] = "add_user_id"
        context.user_data["add_queue_id"] = qid
        await query.edit_message_text(
            "✍️ Введи <b>Telegram ID</b> пользователя (число):\n\n"
            "Например: <code>123456789</code>\n\n"
            "💡 ID можно узнать через @userinfobot",
            parse_mode="HTML",
        )
        return WAITING_ADD_USER_ID


async def handle_member_action(query, context, cmd, mid, user_id):
    member = await get_member_by_id(mid)
    if not member:
        await query.edit_message_text(
            "⚠️ Участник не найден.",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    q = await get_queue(member["queue_id"])
    name = html.escape(member["display_name"])

    if cmd == "movefront":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Нет прав.")
        result = await move_to_front(mid, member["queue_id"], user_id)
        if not result:
            text = "⚠️ Не удалось переместить."
        else:
            text = f"⬆️ <b>{name}</b> перемещён в начало очереди!\n\n" + await fmt_queue(q)
    elif cmd == "missed":
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
            reply_markup=main_menu_keyboard(user_id),
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
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard(user_id))
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

    if is_blocked(user.id):
        await update.message.reply_text("🚫 Ты заблокирован. Обратись к администратору.")
        context.user_data.clear()
        return ConversationHandler.END

    if action == "add_user_id":
        qid = context.user_data.get("add_queue_id")
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ ID должен быть числом. Попробуй ещё раз или /cancel.",
                reply_markup=main_menu_keyboard(user.id),
            )
            context.user_data.clear()
            return ConversationHandler.END
        if uid <= 0:
            await update.message.reply_text(
                "❌ ID должен быть положительным числом. /cancel",
                reply_markup=main_menu_keyboard(user.id),
            )
            context.user_data.clear()
            return ConversationHandler.END
        context.user_data["add_user_id"] = uid
        context.user_data["action"] = "add_user_name"
        await update.message.reply_text(
            "✍️ Теперь введи <b>Имя</b> пользователя:\n\n"
            "Например: <code>Иван</code>",
            parse_mode="HTML",
        )
        return WAITING_ADD_USER_NAME

    if action == "add_user_name":
        uid = context.user_data.get("add_user_id")
        qid = context.user_data.get("add_queue_id")
        name = text.strip()
        if not name:
            await update.message.reply_text(
                "❌ Имя не может быть пустым. /cancel",
                reply_markup=main_menu_keyboard(user.id),
            )
            context.user_data.clear()
            return ConversationHandler.END
        if len(name) > 50:
            await update.message.reply_text(
                "❌ Имя слишком длинное (макс. 50). /cancel",
                reply_markup=main_menu_keyboard(user.id),
            )
            context.user_data.clear()
            return ConversationHandler.END
        await set_user_profile(uid, "", name)
        if qid:
            await join_queue_force(qid, uid, "", name)
            q = await get_queue(qid)
            qtitle = html.escape(q["title"]) if q else "?"
            await update.message.reply_text(
                f"✅ <b>{html.escape(name)}</b> (<code>{uid}</code>) добавлен"
                f" в очередь <b>{qtitle}</b>!\n\n"
                f"Теперь бот сможет писать ему уведомления.",
                parse_mode="HTML",
                reply_markup=back_to_queue_keyboard(qid),
            )
        else:
            await update.message.reply_text(
                f"✅ <b>{html.escape(name)}</b> (<code>{uid}</code>) зарегистрирован!\n\n"
                f"Теперь бот сможет писать ему уведомления.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(user.id),
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
                reply_markup=main_menu_keyboard(user.id),
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
        reply_markup=main_menu_keyboard(user.id),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    await update.message.reply_text(
        "Отменено. Возвращаю в главное меню.",
        reply_markup=main_menu_keyboard(user_id),
    )
    return ConversationHandler.END


async def miss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

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
    loop.run_until_complete(reload_permissions())

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            WAITING_QUEUE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_input)
            ],
            WAITING_ADD_USER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_input)
            ],
            WAITING_ADD_USER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("miss", miss_command))
    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)

    print("✅ Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
