import html


def esc(text):
    return html.escape(str(text))


def _progress_bar(current, total, width=10):
    if total == 0:
        return "▱" * width
    filled = round((current / total) * width)
    return "▰" * filled + "▱" * (width - filled)


async def fmt_queue(queue):
    from data import get_active_members, get_queue_stats

    queue_id = queue["id"]
    title = esc(queue["title"])
    members = await get_active_members(queue_id)
    stats = await get_queue_stats(queue_id)
    total_active = len(members)

    header = f"<b>📌 {title}</b>"
    if total_active > 0:
        header += f"  <i>({total_active} чел.)</i>"

    lines = [header, ""]

    if not members:
        lines.append("✨ Очередь пуста. Будешь первым?")
    else:
        for i, m in enumerate(members, start=1):
            name = esc(m["display_name"])
            if i == 1:
                lines.append(f"🟢 <b>{i}. {name}</b>  ← следующий")
            else:
                lines.append(f"  {i}. {name}")

    if stats:
        done = stats["done"]
        failed = stats["failed"]
        missed = stats["missed"]
        total = stats["total"]
        if total > 0:
            lines.append("")
            parts = []
            if done:
                parts.append(f"✅ {done} прошли")
            if failed:
                parts.append(f"⏰ {failed} не успели")
            if missed:
                parts.append(f"🚫 {missed} не явились")
            lines.append("  " + "  ".join(parts))

    return "\n".join(lines)


async def fmt_passed(queue):
    from data import get_passed_members

    queue_id = queue["id"]
    title = esc(queue["title"])
    passed = await get_passed_members(queue_id)
    count = len(passed)

    lines = [f"<b>✅ Прошли: {title}</b>", ""]

    if not passed:
        lines.append("Никто ещё не прошёл.")
    else:
        lines.append(f"Всего прошло: <b>{count}</b>\n")
        for i, m in enumerate(passed, start=1):
            lines.append(f"✔️ {i}. {esc(m['display_name'])}")

    return "\n".join(lines)


async def fmt_stats(queue):
    from data import get_queue_stats

    stats = await get_queue_stats(queue["id"])
    title = esc(queue["title"])
    total = stats["total"]

    lines = [
        f"<b>📊 Статистика: {title}</b>",
        "",
        f"Всего участников: <b>{total}</b>",
        "",
    ]

    items = [
        ("🟢 Активных", stats["active"]),
        ("✅ Прошли", stats["done"]),
        ("⏰ Не успели", stats["failed"]),
        ("🚫 Не явились", stats["missed"]),
        ("🗑 Удалены", stats["removed"]),
    ]

    for emoji_label, count in items:
        bar = _progress_bar(count, total) if total > 0 else "▱" * 10
        lines.append(f"{emoji_label}: <b>{count}</b>  {bar}")

    return "\n".join(lines)


async def fmt_my_position(queue, member):
    from data import get_active_members

    title = esc(queue["title"])
    name = esc(member["display_name"])

    members = await get_active_members(queue["id"])
    pos = 0
    for i, m in enumerate(members, start=1):
        if m["id"] == member["id"]:
            pos = i
            break

    lines = [
        "👤 <b>Твоя запись</b>",
        "",
        f"Очередь: <b>{title}</b>",
        f"Имя: {name}",
        f"Позиция: <b>{pos}</b>",
        f"Перед тобой: <b>{pos - 1}</b> чел.",
        "",
    ]

    if pos == 1:
        lines.append("🎯 Ты следующий! Готовься.")
    elif pos <= 3:
        lines.append("🔥 Скоро твой черёд!")
    elif pos <= 5:
        lines.append("⏳ Ещё немного — и ты.")
    else:
        lines.append("💪 Держись, дождёшься!")

    return "\n".join(lines)
