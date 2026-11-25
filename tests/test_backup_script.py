"""The backup script: safe writing, permissions and rotation."""

import gzip
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup_db.sh"


def run(tmp_path, dump="echo SELECT_1;", keep="14", args=None):
    env = {**os.environ, "DUMP_COMMAND": dump, "BACKUP_KEEP_DAYS": keep}
    return subprocess.run(
        ["bash", str(SCRIPT), *(args if args is not None else [str(tmp_path / "b")])],
        env=env, capture_output=True, text=True, timeout=30,
    )


def backups(tmp_path):
    return sorted(p for p in (tmp_path / "b").glob("peligrosa-*.sql.gz"))


def age(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_a_good_backup_is_complete_private_and_readable(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    (file,) = backups(tmp_path)
    assert gzip.open(file, "rt").read().strip() == "SELECT_1;"
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert not list((tmp_path / "b").glob(".*"))  # no temporary leftovers


def test_old_backups_are_deleted_and_recent_ones_kept(tmp_path):
    run(tmp_path)
    folder = tmp_path / "b"
    old, recent, other = folder / "peligrosa-old.sql.gz", folder / "peligrosa-recent.sql.gz", folder / "notes.txt"
    for f in (old, recent, other):
        f.write_text("x")
    age(old, 30)
    age(recent, 5)
    age(other, 90)

    assert run(tmp_path, keep="14").returncode == 0
    assert not old.exists() and recent.exists()
    assert other.exists()  # only our own backup files are ever touched


def test_a_failing_dump_keeps_every_old_backup_and_leaves_no_partial_file(tmp_path):
    run(tmp_path)
    folder = tmp_path / "b"
    old = folder / "peligrosa-old.sql.gz"
    old.write_text("x")
    age(old, 100)

    result = run(tmp_path, dump="false")
    assert result.returncode != 0
    assert old.exists()
    assert len(backups(tmp_path)) == 2
    assert not list(folder.glob(".*"))


def test_an_empty_dump_is_an_error_and_deletes_nothing(tmp_path):
    run(tmp_path)
    folder = tmp_path / "b"
    old = folder / "peligrosa-old.sql.gz"
    old.write_text("x")
    age(old, 100)

    result = run(tmp_path, dump="true")
    assert result.returncode == 1 and "empty" in result.stderr
    assert old.exists()


def test_a_dump_that_fails_halfway_is_not_kept(tmp_path):
    dump = tmp_path / "dump.sh"
    dump.write_text("echo partial output\nexit 3\n")
    result = run(tmp_path, dump=f"bash {dump}")
    assert result.returncode == 3  # the dump's own failure is passed on
    assert backups(tmp_path) == []


def test_a_bad_retention_setting_is_refused(tmp_path):
    for bad in ("abc", "-1", "1.5", "7d"):
        result = run(tmp_path, keep=bad)
        assert result.returncode == 2, bad


def test_the_backup_folder_comes_from_the_argument_or_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "from_env"))
    assert run(tmp_path, args=[]).returncode == 0
    assert list((tmp_path / "from_env").glob("peligrosa-*.sql.gz"))
    assert run(tmp_path, args=[str(tmp_path / "from_arg")]).returncode == 0
    assert list((tmp_path / "from_arg").glob("peligrosa-*.sql.gz"))
