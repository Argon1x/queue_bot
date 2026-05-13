import asyncio
import json
from db import fetchrow, execute

QUEUES_JSON = "queues.json"


async def migrate():
    with open(QUEUES_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    for title, qdata in data.items():
        row = await fetchrow(
            "SELECT id FROM queues WHERE title = $1 AND is_active = TRUE", title
        )
        if not row:
            print(f"Queue '{title}' not found in DB, skipping")
            continue
        qid = row["id"]

        passed = qdata.get("passed", [])
        for name in passed:
            existing = await fetchrow(
                "SELECT id FROM queue_members WHERE queue_id = $1 AND display_name = $2 AND telegram_user_id = 0",
                qid, name,
            )
            if not existing:
                await execute(
                    "INSERT INTO queue_members (queue_id, telegram_user_id, username, display_name, status) "
                    "VALUES ($1, 0, '', $2, 'done')",
                    qid, name,
                )
                print(f"  + {name} -> done (legacy)")

    print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
