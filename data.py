import json

from db import fetch, fetchrow, execute
from config import DEFAULT_QUEUES


async def init_db():
    await execute(
        "CREATE TABLE IF NOT EXISTS user_profiles ("
        "telegram_user_id BIGINT PRIMARY KEY,"
        "display_name TEXT NOT NULL,"
        "username TEXT DEFAULT '',"
        "created_at TIMESTAMPTZ DEFAULT NOW()"
        ")"
    )
    try:
        await execute("ALTER TABLE queue_members ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0")
        await execute("UPDATE queue_members SET sort_order = id WHERE sort_order = 0")
    except Exception:
        pass
    await execute(
        "CREATE TABLE IF NOT EXISTS bot_admins ("
        "telegram_user_id BIGINT PRIMARY KEY,"
        "created_by BIGINT NOT NULL DEFAULT 0,"
        "created_at TIMESTAMPTZ DEFAULT NOW()"
        ")"
    )
    await execute(
        "CREATE TABLE IF NOT EXISTS blocked_users ("
        "telegram_user_id BIGINT PRIMARY KEY,"
        "blocked_by BIGINT NOT NULL DEFAULT 0,"
        "blocked_at TIMESTAMPTZ DEFAULT NOW()"
        ")"
    )
    for title in DEFAULT_QUEUES:
        exists = await fetchrow(
            "SELECT id FROM queues WHERE title = $1 AND is_active = TRUE", title
        )
        if not exists:
            await execute(
                "INSERT INTO queues (title, chat_id, created_by) VALUES ($1, 0, 0)",
                title,
            )


async def get_queues():
    rows = await fetch(
        "SELECT id, title FROM queues WHERE is_active = TRUE ORDER BY id"
    )
    return [(r["id"], r["title"]) for r in rows]


async def get_queue(queue_id: int):
    return await fetchrow(
        "SELECT id, title, is_active FROM queues WHERE id = $1", queue_id
    )


async def create_queue(title: str, created_by: int = 0):
    existing = await fetchrow(
        "SELECT id FROM queues WHERE title = $1 AND is_active = TRUE", title
    )
    if existing:
        return None
    row = await fetchrow(
        "INSERT INTO queues (title, created_by) VALUES ($1, $2) RETURNING id",
        title,
        created_by,
    )
    await _log_event(row["id"], created_by, "create", None, None)
    return row["id"]


async def delete_queue(queue_id: int, actor: int = 0):
    q = await get_queue(queue_id)
    if not q:
        return False
    await execute("UPDATE queues SET is_active = FALSE WHERE id = $1", queue_id)
    await _log_event(queue_id, actor, "delete", None, None)
    return True


async def join_queue(queue_id: int, user_id: int, username: str, display_name: str):
    q = await get_queue(queue_id)
    if not q:
        return "not_found"
    existing = await fetchrow(
        "SELECT id FROM queue_members WHERE queue_id = $1 AND telegram_user_id = $2 AND status = 'active'",
        queue_id,
        user_id,
    )
    if existing:
        return "already"
    max_sort = await fetchrow(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort FROM queue_members WHERE queue_id = $1",
        queue_id,
    )
    next_sort = max_sort["next_sort"] if max_sort else 1
    row = await fetchrow(
        "INSERT INTO queue_members (queue_id, telegram_user_id, username, display_name, status, sort_order) "
        "VALUES ($1, $2, $3, $4, 'active', $5) RETURNING id",
        queue_id,
        user_id,
        username,
        display_name,
        next_sort,
    )
    pos = await _get_position(queue_id, row["id"])
    await _log_event(queue_id, user_id, "join", None, "active", meta={"member_id": row["id"]})
    return pos


async def join_queue_force(queue_id: int, user_id: int, username: str, display_name: str):
    existing = await fetchrow(
        "SELECT id FROM queue_members WHERE queue_id = $1 AND display_name = $2 AND status = 'active'",
        queue_id, display_name,
    )
    if existing:
        await execute(
            "UPDATE queue_members SET telegram_user_id = $1, username = $2 WHERE id = $3",
            user_id, username, existing["id"],
        )
        return await _get_position(queue_id, existing["id"])
    return await join_queue(queue_id, user_id, username, display_name)


async def leave_queue(queue_id: int, user_id: int):
    row = await fetchrow(
        "SELECT id FROM queue_members WHERE queue_id = $1 AND telegram_user_id = $2 AND status = 'active'",
        queue_id,
        user_id,
    )
    if not row:
        return False
    await execute(
        "UPDATE queue_members SET status = 'removed', updated_at = NOW() WHERE id = $1",
        row["id"],
    )
    await _log_event(queue_id, user_id, "leave", "active", "removed", meta={"member_id": row["id"]})
    return True


async def mark_done(queue_id: int, actor: int = 0):
    first = await fetchrow(
        "SELECT id, telegram_user_id, display_name FROM queue_members "
        "WHERE queue_id = $1 AND status = 'active' ORDER BY id LIMIT 1",
        queue_id,
    )
    if not first:
        return None
    await execute(
        "UPDATE queue_members SET status = 'done', updated_at = NOW() WHERE id = $1",
        first["id"],
    )
    await _log_event(queue_id, actor, "mark_done", "active", "done", meta={"member_id": first["id"]})
    return first


async def mark_missed(member_id: int, actor: int = 0):
    row = await fetchrow(
        "SELECT id, queue_id, display_name FROM queue_members WHERE id = $1 AND status = 'active'",
        member_id,
    )
    if not row:
        return None
    await execute(
        "UPDATE queue_members SET status = 'missed', updated_at = NOW() WHERE id = $1",
        row["id"],
    )
    await _log_event(row["queue_id"], actor, "mark_missed", "active", "missed", meta={"member_id": row["id"]})
    return row


async def mark_failed(queue_id: int, actor: int = 0):
    first = await fetchrow(
        "SELECT id, telegram_user_id, display_name FROM queue_members "
        "WHERE queue_id = $1 AND status = 'active' ORDER BY id LIMIT 1",
        queue_id,
    )
    if not first:
        return None
    await execute(
        "UPDATE queue_members SET status = 'failed', updated_at = NOW() WHERE id = $1",
        first["id"],
    )
    await _log_event(queue_id, actor, "mark_failed", "active", "failed", meta={"member_id": first["id"]})
    return first


async def return_to_queue(member_id: int, actor: int = 0):
    row = await fetchrow(
        "SELECT id, queue_id, display_name, status FROM queue_members WHERE id = $1",
        member_id,
    )
    if not row or row["status"] == "active":
        return None
    await execute(
        "UPDATE queue_members SET status = 'active', updated_at = NOW() WHERE id = $1",
        row["id"],
    )
    await _log_event(
        row["queue_id"], actor, "return", row["status"], "active", meta={"member_id": row["id"]}
    )
    return row


async def remove_member(member_id: int, actor: int = 0):
    row = await fetchrow("SELECT id, queue_id, display_name, status FROM queue_members WHERE id = $1", member_id)
    if not row:
        return None
    await execute(
        "UPDATE queue_members SET status = 'removed', updated_at = NOW() WHERE id = $1",
        row["id"],
    )
    await _log_event(
        row["queue_id"], actor, "remove", row["status"], "removed", meta={"member_id": row["id"]}
    )
    return row


async def get_active_members(queue_id: int):
    return await fetch(
        "SELECT id, telegram_user_id, username, display_name FROM queue_members "
        "WHERE queue_id = $1 AND status = 'active' ORDER BY sort_order, id",
        queue_id,
    )


async def get_passed_members(queue_id: int):
    return await fetch(
        "SELECT id, telegram_user_id, username, display_name FROM queue_members "
        "WHERE queue_id = $1 AND status = 'done' ORDER BY id",
        queue_id,
    )


async def get_member_by_id(member_id: int):
    return await fetchrow(
        "SELECT id, queue_id, telegram_user_id, display_name, status FROM queue_members WHERE id = $1",
        member_id,
    )


async def get_my_membership(queue_id: int, user_id: int):
    return await fetchrow(
        "SELECT id, display_name, status FROM queue_members "
        "WHERE queue_id = $1 AND telegram_user_id = $2 AND status = 'active'",
        queue_id,
        user_id,
    )


async def _get_position(queue_id: int, member_id: int):
    row = await fetchrow(
        "SELECT COUNT(*) AS pos FROM queue_members "
        "WHERE queue_id = $1 AND status = 'active' AND id <= $2",
        queue_id,
        member_id,
    )
    return row["pos"] if row else 0


async def _log_event(queue_id, actor, action, old_status, new_status, meta=None):
    await execute(
        "INSERT INTO queue_events (queue_id, actor_user_id, action, old_status, new_status, meta) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        queue_id,
        actor,
        action,
        old_status,
        new_status,
        json.dumps(meta or {}),
    )


async def admin_clear_queue(queue_id: int, actor: int = 0):
    await execute(
        "UPDATE queue_members SET status = 'removed', updated_at = NOW() "
        "WHERE queue_id = $1 AND status = 'active'",
        queue_id,
    )
    await _log_event(queue_id, actor, "clear", "active", "removed")


async def get_all_profiles():
    return await fetch(
        "SELECT telegram_user_id, display_name, username, created_at "
        "FROM user_profiles ORDER BY display_name"
    )


async def set_user_profile(user_id: int, username: str, display_name: str):
    await execute(
        "INSERT INTO user_profiles (telegram_user_id, username, display_name) "
        "VALUES ($1, $2, $3) "
        "ON CONFLICT (telegram_user_id) DO UPDATE SET "
        "display_name = EXCLUDED.display_name, username = EXCLUDED.username",
        user_id, username, display_name,
    )
    await execute(
        "UPDATE queue_members SET telegram_user_id = $1 "
        "WHERE display_name = $2 AND telegram_user_id = 0",
        user_id, display_name,
    )


async def get_user_profile(user_id: int):
    return await fetchrow(
        "SELECT * FROM user_profiles WHERE telegram_user_id = $1", user_id
    )


async def get_next_member(queue_id: int):
    return await fetchrow(
        "SELECT id, telegram_user_id, display_name FROM queue_members "
        "WHERE queue_id = $1 AND status = 'active' ORDER BY id LIMIT 1",
        queue_id,
    )


async def add_bot_admin(uid: int, created_by: int):
    await execute(
        "INSERT INTO bot_admins (telegram_user_id, created_by) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING",
        uid, created_by,
    )


async def remove_bot_admin(uid: int):
    await execute(
        "DELETE FROM bot_admins WHERE telegram_user_id = $1", uid
    )


async def get_bot_admins():
    return await fetch(
        "SELECT telegram_user_id FROM bot_admins"
    )


async def block_user(uid: int, blocked_by: int):
    await execute(
        "INSERT INTO blocked_users (telegram_user_id, blocked_by) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING",
        uid, blocked_by,
    )


async def unblock_user(uid: int):
    await execute(
        "DELETE FROM blocked_users WHERE telegram_user_id = $1", uid
    )


async def get_blocked_users():
    return await fetch(
        "SELECT telegram_user_id FROM blocked_users"
    )


async def move_to_front(member_id: int, queue_id: int, actor: int = 0):
    member = await fetchrow(
        "SELECT id, queue_id, display_name, status FROM queue_members WHERE id = $1 AND queue_id = $2",
        member_id, queue_id,
    )
    if not member or member["status"] != "active":
        return None
    current_sort = await fetchrow(
        "SELECT sort_order FROM queue_members WHERE id = $1", member_id,
    )
    if not current_sort:
        return None
    current_pos = current_sort["sort_order"]
    if current_pos == 1:
        return member
    await execute(
        "UPDATE queue_members SET sort_order = sort_order + 1 "
        "WHERE queue_id = $1 AND status = 'active' AND sort_order < $2",
        queue_id, current_pos,
    )
    await execute(
        "UPDATE queue_members SET sort_order = 1 WHERE id = $1", member_id,
    )
    await _log_event(queue_id, actor, "move_to_front", None, None, meta={"member_id": member_id})
    return member


async def get_queue_stats(queue_id: int):
    return await fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'active') AS active,
            COUNT(*) FILTER (WHERE status = 'done') AS done,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed,
            COUNT(*) FILTER (WHERE status = 'missed') AS missed,
            COUNT(*) FILTER (WHERE status = 'removed') AS removed,
            COUNT(*) AS total
        FROM queue_members WHERE queue_id = $1
        """,
        queue_id,
    )
