from config import ADMIN_IDS

_db_admins: set[int] = set()
_blocked: set[int] = set()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in _db_admins


def is_blocked(user_id: int) -> bool:
    return user_id in _blocked


def is_super_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def reload_permissions():
    from data import get_bot_admins, get_blocked_users
    _db_admins.clear()
    for row in await get_bot_admins():
        _db_admins.add(row["telegram_user_id"])
    _blocked.clear()
    for row in await get_blocked_users():
        _blocked.add(row["telegram_user_id"])
