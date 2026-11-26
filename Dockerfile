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
COPY scripts ./scripts

# Not root.
RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /app/data/images \
    && chown -R bot:bot /app/data
USER bot

# "docker ps" shows healthy/unhealthy from the bot's own /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"

# Apply database migrations, then run the Telegram bot (long polling).
CMD ["sh", "-c", "alembic upgrade head && python -m app.telegram"]
