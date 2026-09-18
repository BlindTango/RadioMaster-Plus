"""Unlimited retention must never prune downloaded episodes."""

from unittest.mock import MagicMock

from radiomaster.services.scheduler_service import SchedulerService


def test_unlimited_retention_does_not_touch_database_or_files(monkeypatch):
    db = MagicMock()
    remove = MagicMock()
    monkeypatch.setattr("os.remove", remove)
    SchedulerService._enforce_episode_retention(db, -1)
    assert db.mock_calls == []
    remove.assert_not_called()


def test_finite_retention_still_prunes_old_downloads(tmp_path):
    newest = tmp_path / "new.mp3"
    oldest = tmp_path / "old.mp3"
    notes = tmp_path / "old.txt"
    for file in (newest, oldest, notes):
        file.write_text("content")
    db = MagicMock()
    db.fetchall.side_effect = [
        [{"podcast_id": 1}],
        [{"id": 2, "audio_url": "new", "file_path": str(newest)},
         {"id": 1, "audio_url": "old", "file_path": str(oldest)}],
    ]
    SchedulerService._enforce_episode_retention(db, 1)
    assert newest.exists()
    assert not oldest.exists()
    assert not notes.exists()
    assert db.execute.call_args_list[0].args[1] == (1,)
    assert db.execute.call_args_list[1].args[1] == ("old",)
    db.commit.assert_called_once()
