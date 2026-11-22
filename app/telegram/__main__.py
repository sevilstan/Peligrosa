import asyncio

from app.core.logging_config import setup_logging
from app.telegram.bot import run

if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
