# 📋 Queue Bot — Telegram бот очередей

Управление очередями (ОАИП, Проектная деятельность) через Telegram.

## Структура

```
queue_bot/
├── bot.py           — точка входа
├── config.py        — переменные окружения
├── db.py            — asyncpg connection pool
├── data.py          — слой данных (PostgreSQL)
├── permissions.py   — проверка админ-прав
├── keyboards.py     — inline-клавиатуры
├── helpers.py       — форматирование (HTML)
├── requirements.txt
├── Dockerfile
├── Procfile
├── .gitignore
└── .env.example
```

## Переменные окружения

```env
TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://user:password@host:5432/queue_bot
ADMIN_IDS=123456789,987654321
DEFAULT_QUEUES=ОАИП,Проектная деятельность
ENV=production
LOG_LEVEL=INFO
```

## Локальный запуск

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполни .env
python bot.py
```

## Docker

```bash
docker build -t queue-bot .
docker run --env-file .env queue-bot
```

## Railway

1. Подключи репозиторий
2. Добавь переменные окружения
3. Deploy
