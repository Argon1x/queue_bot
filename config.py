import os

TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")

if not TOKEN:
    raise ValueError("TOKEN environment variable is required")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]
DEFAULT_QUEUES = ["ОАИП", "Проектная деятельность"]
