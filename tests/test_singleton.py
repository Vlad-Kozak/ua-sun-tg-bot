"""Два процеси з одним токеном крадуть один в одного апдейти (Conflict)."""

from __future__ import annotations

import logging

from bot.utils.singleton import InstanceLock


def test_second_instance_cannot_start(tmp_path, caplog):
    path = tmp_path / "bot.lock"
    first = InstanceLock(path)
    assert first.acquire() is True

    with caplog.at_level(logging.ERROR):
        assert InstanceLock(path).acquire() is False
    assert "уже запущений" in caplog.records[0].getMessage()

    first.release()


def test_lock_is_reusable_after_release(tmp_path):
    path = tmp_path / "bot.lock"
    first = InstanceLock(path)
    assert first.acquire() is True
    first.release()

    second = InstanceLock(path)
    assert second.acquire() is True
    second.release()


def test_lock_file_records_pid(tmp_path):
    path = tmp_path / "bot.lock"
    lock = InstanceLock(path)
    lock.acquire()

    assert path.read_text().startswith("pid=")
    lock.release()


def test_missing_directory_is_created(tmp_path):
    path = tmp_path / "deep" / "nested" / "bot.lock"
    lock = InstanceLock(path)

    assert lock.acquire() is True
    assert path.exists()
    lock.release()


def test_context_manager_releases(tmp_path):
    path = tmp_path / "bot.lock"
    with InstanceLock(path) as lock:
        assert lock.acquire() is True

    assert InstanceLock(path).acquire() is True


def test_release_without_acquire_is_safe(tmp_path):
    InstanceLock(tmp_path / "bot.lock").release()
