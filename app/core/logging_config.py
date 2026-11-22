import logging

from app.core.config import settings


def setup_logging() -> None:
    """Configure application logging once.

    Rules for what may be logged anywhere in the app:
    - never API keys;
    - never user message text or memory content (database errors can
      contain statement parameters, so log the error type instead).
    """
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # httpx logs every request URL at INFO; keep it quiet unless debugging.
    if not settings.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
