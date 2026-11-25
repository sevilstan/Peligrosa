# Running Peligrosa (Telegram bot)

The bot uses long polling: it needs outbound internet only (Telegram, Groq),
no public address, no webhook, no open port.

## 1. What you need

- A Telegram bot token (BotFather).
- A Groq API key.
- A machine with Docker (any small VPS is enough to start).

## 2. First start

```bash
git clone https://github.com/sevilstan/Peligrosa.git && cd Peligrosa
cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, GROQ_API_KEY, POSTGRES_PASSWORD
docker compose up -d --build
docker compose logs -f bot
```

On every start the bot container first runs `alembic upgrade head` (applies
new migrations, never destructive on its own), then starts the bot. Characters
come from the `characters/` YAML files: every time the bot starts it creates
the database row of each new YAML file (so it shows up in Telegram) and
refreshes the texts of existing ones. A character you deactivated stays
inactive; nothing is ever deleted. To do it by hand: `python -m scripts.sync_characters`.

> `docker-compose.yml` and the Dockerfile were written but **not built or run
> in the development session** (no Docker daemon there). Run the first start
> yourself and watch the log before announcing the bot.

## 3. Updating

```bash
git pull
docker compose up -d --build   # migrations run automatically
```

## Credits (free trial, credits, subscription)

Off by default (`CREDITS_ENABLED=false` = no limits). **Turn it on in
production**, otherwise cost is unbounded. When on: a new user gets
`TRIAL_CREDITS` once, a message costs `MESSAGE_COST`, a group message
`GROUP_MESSAGE_COST`, creating a group `GROUP_CREATE_COST` (free for
subscribers). A failed AI reply is refunded. Users see their balance with
`/credits`. An operator listed in `ADMIN_TELEGRAM_IDS` can give credits with
`/grant <telegram_id> <credits>`.

### Selling with Telegram Stars

`/buy` shows what is on sale; payment is in Stars only (Telegram requires it
for digital goods, no payment provider token is needed). Everything is set in
`.env`: `CREDIT_PACKS` (`credits:stars,...`), `SUB_PRICE_STARS`, `SUB_DAYS`,
`SUB_DAILY_MESSAGE_CAP`, `SUB_GROUP_CREATE_FREE`, `SUB_BONUS_CREDITS`.
Nothing is unlimited: a subscriber has a daily message cap.

- Telegram approves each payment with us for only 10 seconds; the bot answers
  quickly and delivers only after `successful_payment`.
- Delivery is idempotent (the Telegram charge id is unique) and saved in one
  transaction with the credits. A payment for something no longer on sale is
  stored as `needs_review` and logged as an error with its charge id.
- `/refund <telegram_charge_id>` (operators): Telegram returns the Stars first;
  only if that works the credits/subscription days are taken back.
- Telegram requires `/terms`, `/support` and `/paysupport`. Set
  `SUPPORT_CONTACT`, and have a professional review the terms text in
  `app/telegram/texts.py` (`terms_text`) before going live. You are responsible
  for disputes. Test payments in Telegram's test environment first.

## Monitoring basics

- `GET /health` answers 200 when the bot's database works, 503 otherwise;
  `GET /stats` shows AI calls, failures, average seconds and prompt/answer
  sizes per day (no user text). Enable with `HEALTH_PORT` (compose sets 8080,
  reachable only inside the container; `docker ps` shows healthy/unhealthy).
- Point an uptime service at `/health` through a reverse proxy only if you
  need outside checks; never publish the port directly.
- Counters live in memory and restart with the bot. Error alerts (e.g.
  Sentry) and database backups are separate, still-open items.

## 4. Rate limits and cost (important before real users)

All AI calls go through one limiter (`AI_MAX_REQUESTS_PER_MINUTE`, default 25
for Groq's free 30/min). Extra requests wait in line (the user sees "typing...");
after `AI_MAX_QUEUE_WAIT_SECONDS` (60) the user gets "try again".

Calls per user message: direct chat about 2-3 (reply, memory extraction,
sometimes a summary). Group chat with 4 members: up to 1 speaker choice + 4
replies + 1 memory extraction, plus a feelings reflection every 8 messages and
a character-to-character exchange in about 1 of 4 messages (up to 3 more calls).

So the free tier supports **a few active group users at a time**. Before a
public launch: a paid tier (raise the limits), or a cheaper model for the small
helper calls. Limits are per process: run ONE bot process per API key.

## 5. Database connections

A reply keeps its database connection while the AI answers, so
`DB_POOL_SIZE + DB_MAX_OVERFLOW` (default 10 + 20) is the number of
conversations that can be in flight. PostgreSQL's default limit is 100
connections; keep the sum well below it.

## 6. Backups

User conversations and memories live in the `pgdata` volume. Back it up:

```bash
docker compose exec db pg_dump -U peligrosa peligrosa | gzip > peligrosa-$(date +%F).sql.gz
```

## 7. Secrets and logs

- `.env` is never committed. Rotate a token that was ever pasted into a chat or log.
- Logs contain error types and counts, never message text or API keys.
  Keep `DEBUG=False` and `SQL_ECHO=False` in production.

## 8. Not done yet (decisions for the owner)

- Per-user message limits (anti-abuse, daily free quota, payment).
- Monitoring/alerts (the container restarts itself; nobody is told).
- A second process or webhook mode (needed only at larger scale).
