"""A tiny HTTP endpoint so something outside can ask "is the bot alive?".

GET /health -> 200 {"status": "ok"} when the database answers, else 503.
GET /stats  -> AI usage counters per day (no user data).

Off unless HEALTH_PORT is set. Binds to HEALTH_HOST (default 127.0.0.1): the
Docker health check and a reverse proxy on the same machine can reach it, the
internet cannot.
"""

import logging

from aiohttp import web
from sqlalchemy import text

logger = logging.getLogger(__name__)


def build_health_app(session_maker, usage_provider=None) -> web.Application:
    async def health(_request):
        try:
            async with session_maker() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.error("Health check: database unreachable: %s", type(exc).__name__)
            return web.json_response({"status": "database_down"}, status=503)
        return web.json_response({"status": "ok"})

    async def stats(_request):
        data = usage_provider.snapshot() if usage_provider is not None else {}
        return web.json_response({"ai_usage": data})

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/stats", stats)
    return app


async def start_health_server(session_maker, usage_provider, host: str, port: int):
    runner = web.AppRunner(build_health_app(session_maker, usage_provider))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    logger.info("Health endpoint listening on %s:%d", host, port)
    return runner
