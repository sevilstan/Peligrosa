FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY app ./app
COPY migrations ./migrations
COPY characters ./characters

# Not root.
RUN useradd --create-home --uid 10001 bot
USER bot

# Apply database migrations, then run the Telegram bot (long polling).
CMD ["sh", "-c", "alembic upgrade head && python -m app.telegram"]
