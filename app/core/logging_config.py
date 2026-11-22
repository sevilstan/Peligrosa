import logging

from app.core.config import settings

# Libraries that log request details at DEBUG/INFO (URLs, response headers
# with cookies, connection internals). Never useful here, so always quiet.
_NOISY_LIBRARIES = ("httpx", "httpcore", "openai", "asyncio", "aiohttp")


def setup_logging() -> None:
    """Configure application logging once.

    DEBUG only affects our own loggers (app.*). SQL statements are shown
    only when SQL_ECHO is on, because their parameters contain user text.

    Rules for what may be logged anywhere in the app:
    - never API keys;
    - never user message text or memory content (database errors can
      contain statement parameters, so log the error type instead).
    """
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # basicConfig does nothing when handlers already exist, so be explicit.
    logging.getLogger().setLevel(level)

    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.SQL_ECHO else logging.WARNING
    )
