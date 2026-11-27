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
`/grant <telegram_id> <credits>`. Operators are never charged themselves
(messages, groups, pictures), so they can test everything freely.

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

## Privacy: /deletedata

A user can delete all their data with `/deletedata` (two steps: warning, then a
confirm button). It removes every chat and message, the characters' memories of
the user, the user's own memory records, and the relationship/mood data. It
keeps the account row (Telegram id, credit balance, subscription end) and the
credit/payment records: payment records may have to be kept by law, and
keeping the row stops a deleted account from taking a new free trial. The user
is told this before confirming. Backups taken earlier still contain the old
data until they expire: set a backup retention period and say so in your
privacy policy. Data export is not implemented yet.

### Training data and backups

Chats may be used to train models (the terms say so, and say that deleting
removes the data from training data and backups). To keep that promise:

- Build datasets only with `python -m scripts.export_training_data --out
  file.jsonl`: it skips users who used `/deletedata` (and deactivated users)
  and replaces user ids with pseudonyms (needs `TRAINING_EXPORT_SALT`). Chat
  text can still contain personal details: protect exports like personal data.
- Before each new training run, run `--deleted-pseudonyms` and remove those
  users from every older export you keep.
- After **restoring a backup**, run `python -m scripts.reapply_deletions
  <file>`; the bot logs `User data deleted: user_id=...` for every deletion, so
  `grep "User data deleted" bot.log > deleted_users.txt` is enough. Keep these
  log lines for as long as you keep backups. Delete old backups on a schedule.
- A model that was already trained on someone's chats cannot be "untrained":
  decide the policy for that with a legal adviser before the first training run.

### Operator commands

Only Telegram ids in `ADMIN_TELEGRAM_IDS` can use them; everyone else just
gets "unknown command".
- `/stats`: last-24-hour users, messages, credits spent, Stars earned and
  pictures, plus all-time payments and how many pictures the cache saved.
  Counts only, no names or message text.
- `/grant <telegram_id> <credits>`: give credits.
- `/refund <charge id>`: return a Stars payment (see Selling with Telegram Stars).

## Monitoring basics

- `GET /health` answers 200 when the bot's database works, 503 otherwise;
  `GET /stats` shows AI calls, failures, average seconds and prompt/answer
  sizes per day (no user text). Enable with `HEALTH_PORT` (compose sets 8080,
  reachable only inside the container; `docker ps` shows healthy/unhealthy).
- Point an uptime service at `/health` through a reverse proxy only if you
  need outside checks; never publish the port directly.
- Counters live in memory and restart with the bot.
- **Error alerts:** set `ADMIN_TELEGRAM_IDS` and every operator gets a Telegram
  message for each ERROR our code logs (unhandled errors, AI provider failures,
  "payment received but not delivered") and a "Bot started" message after each
  restart. Operators must press /start in the bot once, otherwise Telegram
  refuses the message (logged as a warning). The same problem is sent once per
  `ALERT_DEDUP_SECONDS` with a count of held-back repeats; `ALERT_MAX_PER_HOUR`
  caps the total. Alerts contain the logger name and message only, never a
  traceback or user text. They cannot tell you the whole bot or server is down:
  also point an outside uptime service at `/health`. Database backups are a
  separate, still-open item.

## 4. Rate limits and cost (important before real users)

### Roleplay API provider

Set `AI_PROVIDER=roleplay` and `ROLEPLAY_API_KEY` in `.env` (never in chat or git).
On the trial key use `AI_MAX_CONCURRENT_REQUESTS=2` and
`AI_MAX_REQUESTS_PER_MINUTE=60`; after the first top-up the limits are 8 and 300.
The bot logs an ERROR (operator Telegram alert) on 402 out-of-credit, on 401 bad
key, and when the `X-Balance-USD` header falls below `ROLEPLAY_LOW_BALANCE_USD`
(at most once per 6 hours). Prompts and replies are never logged.

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

### Pictures in chats (Xavira)

How it works: the user presses "Request photo" (or `/photo`), or asks for a
picture in the chat. The bot offers it ("costs N credits, want one?"); on
"yes" the credits are charged, the picture is made and sent. On any failure
the credits are returned. Pictures are for personal chats only, and
subscribers pay credits for them too (messages are what a subscription covers).

Setup:
1. In the Xavira dashboard make one character per person (this costs 1-2
   Xavira credits each) and copy its id.
2. Put it in that character's YAML as `image_character_id: <id>`. The YAML
   must also state `profile: age:` (18 or more); without both, no picture is
   made for that character and the bot says so.
3. In `.env`: `IMAGES_ENABLED=true` and `XAVIRA_API_KEY=...`, then restart.
   `IMAGES_ENABLED=true` without a key stops the bot at startup on purpose.
4. With the provided `docker-compose.yml` the pictures live in the `images`
   volume and survive redeploys. Back that volume up too if you care about
   old pictures (the database only stores their file names).

What goes to Xavira: only a prompt built from a few fixed scene words (setting,
pose, outfit) and the character id. Nothing a user typed is sent. The chat AI
writes those scene words from the recent chat.

Saving Xavira credits: finished pictures are cached per character and scene.
After `IMAGE_CACHE_MIN_VARIANTS` different pictures exist for a scene, other
users asking for the same scene get one of those instead of a new one, and
nobody gets the same picture twice. The user still pays the same credits.
Errors that need you (key rejected, out of credit, unknown character id, low
balance) are logged as ERROR and arrive as operator alerts.

Groups: `/photo` in a group asks "who should send it?" (only members that can be
drawn are listed); the chosen member sends the picture, same price and cache.

Create art: `/art` (or the "Create art" button) asks the user to describe a
picture; they reply with text and are offered it for `ART_COST` credits
(default 10). The text goes to Xavira as written, only cleaned (control
characters removed, at most 300 characters). No word filter on our side:
content moderation is Xavira's job, and a refused picture returns the credits.
These pictures are never cached (each one is a new Xavira call, hence the higher
price) and nothing is written to the logs about the text. The character must
still have an image id and an adult `profile: age:`. They show up in the gallery.

Cost ledger: every picture attempt is written to `image_generations` (user,
character, photo or art, image-service call or cache hit, ok/refused/failed,
provider, model, cost). No prompt or chat text is stored. Set
`XAVIRA_COST_PER_IMAGE` to what one image costs you in Xavira credits to have
cost filled in; `/stats` then shows calls, failures, cache hits, recorded cost
and the characters with the most calls. The ledger is kept after `/deletedata`
(accounting, like credit history).

Delivery: a picture is added to the chat history (and the gallery) only after
Telegram has delivered it. If delivery fails, nothing is saved, the credits are
refunded once and a cached picture is not counted as used. If the photo was
delivered but saving it fails, the user keeps it, nothing is refunded and an
ERROR is logged (operator alert).

My pictures: `/gallery` (or the "My pictures" menu button) shows every picture
the user received as a slider (‹ n/total ›, newest first, up to 200, wraps
around). It reads the picture messages of the user's own chats, so deleting a
chat or using `/deletedata` also removes those pictures from the gallery. If
a file is missing from the `images` volume, that slide is skipped.

## 5. Database connections

A reply keeps its database connection while the AI answers, so
`DB_POOL_SIZE + DB_MAX_OVERFLOW` (default 10 + 20) is the number of
conversations that can be in flight. PostgreSQL's default limit is 100
connections; keep the sum well below it.

## 6. Backups

User conversations, memories and payment records live in the `pgdata` volume.
`scripts/backup_db.sh` writes a compressed dump, checks it, and deletes backups
older than `BACKUP_KEEP_DAYS` (default 14) only after a new good one exists.
Files are readable by their owner only: they contain users' chats.

```bash
# every night at 03:00 (crontab -e), from the project folder on the server:
0 3 * * * cd /srv/peligrosa && scripts/backup_db.sh /srv/backups >> /var/log/peligrosa-backup.log 2>&1
```

- **Copy backups off the server** (another machine or object storage such as
  R2/B2, e.g. with `rclone`); a backup on the same disk dies with the disk.
- **Restore** into an EMPTY database, then re-apply deletions made after the
  backup was taken (users who used `/deletedata` must not come back):

  ```bash
  gunzip -c /srv/backups/peligrosa-<time>.sql.gz | docker compose exec -T db psql -U peligrosa peligrosa
  grep "User data deleted" bot.log > deleted_users.txt   # keep these log lines as long as backups
  docker compose run --rm -v "$PWD/deleted_users.txt:/app/deleted_users.txt:ro" bot \
      python -m scripts.reapply_deletions /app/deleted_users.txt
  ```
- **Test a restore** on a spare machine before you rely on it: a backup you
  never restored is only a hope. Backups are removed after `BACKUP_KEEP_DAYS`;
  your privacy policy should state this retention period.

## 7. Secrets and logs

- `.env` is never committed. Rotate a token that was ever pasted into a chat or log.
- Logs contain error types and counts, never message text or API keys.
  Keep `DEBUG=False` and `SQL_ECHO=False` in production.

## 8. Not done yet (decisions for the owner)

- An outside uptime check on `/health` (alerts cannot report a dead server).
- The first real `docker compose up --build` (the image has not been built in
  the development environment) and a restore test.
- A second process or webhook mode (needed only at larger scale).
