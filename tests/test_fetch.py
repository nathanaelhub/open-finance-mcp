import os
import time

from open_finance_mcp.fetch import CACHE_MAX_AGE, Fetcher


def _touch(path, age_seconds):
    path.write_text("{}", encoding="utf-8")
    t = time.time() - age_seconds
    os.utime(path, (t, t))


def test_prune_removes_only_unservable_cache_files(tmp_path):
    fresh = tmp_path / "fresh.json"
    old = tmp_path / "old.json"
    orphan = tmp_path / "abandoned.tmp"
    in_flight = tmp_path / "being-written.tmp"
    unrelated = tmp_path / "notes.txt"
    _touch(fresh, 29 * 86_400)            # within the 30-day document TTL
    _touch(old, CACHE_MAX_AGE + 60)
    _touch(orphan, 2 * 3600)
    _touch(in_flight, 5)                  # another process may still be writing it
    _touch(unrelated, CACHE_MAX_AGE * 2)  # not ours: never touched

    Fetcher(cache=tmp_path, sec_user_agent="t t@example.com")  # prunes on startup

    assert sorted(p.name for p in tmp_path.iterdir()) == ["being-written.tmp", "fresh.json", "notes.txt"]


def test_prune_tolerates_a_missing_cache_dir(tmp_path):
    f = Fetcher(cache=tmp_path / "does-not-exist", sec_user_agent="t t@example.com")
    assert f.prune_cache() == 0
