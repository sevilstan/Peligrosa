import logging

import pytest

from app.core import logging_config
from app.core.config import settings

LOGGERS = ["", "httpx", "httpcore", "openai", "asyncio", "sqlalchemy.engine"]


@pytest.fixture(autouse=True)
def restore_logger_levels():
    saved = {name: logging.getLogger(name).level for name in LOGGERS}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def level(name):
    return logging.getLogger(name).level


def test_debug_does_not_turn_on_sql_or_library_noise(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "SQL_ECHO", False)

    logging_config.setup_logging()

    assert level("") == logging.DEBUG
    assert level("sqlalchemy.engine") == logging.WARNING
    for name in ("httpx", "httpcore", "openai", "asyncio"):
        assert level(name) == logging.WARNING


def test_sql_echo_turns_sql_on_without_enabling_debug(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "SQL_ECHO", True)

    logging_config.setup_logging()

    assert level("") == logging.INFO
    assert level("sqlalchemy.engine") == logging.INFO


def test_defaults_are_quiet(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "SQL_ECHO", False)

    logging_config.setup_logging()

    assert level("") == logging.INFO
    assert level("sqlalchemy.engine") == logging.WARNING


def test_sql_echo_is_off_by_default():
    assert type(settings).model_fields["SQL_ECHO"].default is False
