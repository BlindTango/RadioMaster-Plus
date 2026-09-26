"""Native list and worker regressions for large station health result sets."""
import threading
import time
from unittest.mock import patch

import pytest
import wx

from radiomaster.services.station_api import Station
from radiomaster.services.station_db import StationDB
from radiomaster.services.station_health import HealthResult, StationHealthService
from radiomaster.ui.station_health_dialog import StationHealthDialog, _HiddenStationsDialog


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        wx.Yield()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def dialog(tmp_path):
    # Navigation tests shut down RadioMasterApp in their teardown. Do not reuse
    # that stopped app (or deliver its old queued callbacks) for these dialogs.
    app = wx.App(False)
    wx.Log.SetActiveTarget(wx.LogStderr())
    db = StationDB(str(tmp_path / "stations.db"))
    # Control the initial load so tests can exercise late callbacks deterministically.
    with patch.object(StationHealthDialog, "_load_persisted_async"):
        dlg = StationHealthDialog(None, db, StationHealthService())
    dlg._drain_timer.Stop()
    yield dlg, db
    if dlg:
        dlg.Destroy()
    wx.Yield()
    dlg._save_thread.join(5)
    dlg._view_thread.join(5)
    assert not dlg._save_thread.is_alive()
    assert not dlg._view_thread.is_alive()


def problem(uuid, name=None, **values):
    return {"uuid": uuid, "_name": name or uuid, "stream_ok": False, **values}


def displayed(dlg):
    return [uuid for uuid, _ in dlg._results_list.rows]


def test_large_virtual_list_preserves_selected_station_and_latest_filter(dialog):
    dlg, _ = dialog
    dlg._results = {str(i): problem(str(i), f"Station {i:05}") for i in range(50000)}
    dlg._refresh_results()
    wait_for(lambda: dlg._results_list.GetItemCount() == 50000)
    assert dlg._results_list.GetWindowStyleFlag() & wx.LC_VIRTUAL
    assert dlg._results_list.GetItemText(25000) == "Station 25000"
    dlg._results_list.Select(25000)
    dlg._results_list.Focus(25000)
    dlg._results["first"] = problem("first", "A First")
    dlg._refresh_results()
    wait_for(lambda: dlg._results_list.GetItemCount() == 50001)
    assert dlg._selected_uuid() == "25000"
    assert dlg._results_list.GetFocusedItem() == 25001
    old_generation = dlg._view_generation
    dlg._filter_choice.SetSelection(2)  # No name mismatches.
    dlg._refresh_results()
    dlg._apply_result_view(old_generation, [("stale", ("Stale", "", ""))])
    wait_for(lambda: dlg._results_list.GetItemCount() == 0)
    assert dlg._detail_text.GetValue() == ""
    assert not dlg._btn_hide.IsEnabled()


def test_hide_all_and_late_results_stay_hidden_until_unhidden(dialog):
    dlg, db = dialog
    db.upsert_stations([Station(uuid=u, name=u, url="http://example.test") for u in ("a", "b")])
    dlg._results = {u: problem(u) for u in ("a", "b")}
    dlg._refresh_results()
    wait_for(lambda: len(displayed(dlg)) == 2)
    with patch("radiomaster.ui.station_health_dialog.wx.MessageBox", return_value=wx.YES):
        dlg._on_hide_all_dead(None)
        wait_for(lambda: not displayed(dlg))
    assert db.hidden_uuids() == {"a", "b"}
    assert not dlg._btn_hide_dead.IsEnabled()
    dlg._apply_recheck(HealthResult(uuid="a", station_name="Latest A", stream_ok=False))
    dlg._apply_persisted_results({"a": problem("a", "Old A")}, {"a", "b"})
    wait_for(lambda: not dlg._save_jobs.unfinished_tasks)
    assert dlg._results["a"]["_name"] == "Latest A"
    assert not displayed(dlg)

    def unhide_all(hidden):
        hidden._on_unhide_all(None)
        return wx.ID_OK
    with patch.object(_HiddenStationsDialog, "ShowModal", unhide_all), \
            patch("radiomaster.ui.station_health_dialog.wx.MessageBox"):
        dlg._on_manage_hidden(None)
    wait_for(lambda: set(displayed(dlg)) == {"a", "b"})
    assert db.hidden_uuids() == set()
    # A load started before Unhide must not hide those stations again.
    dlg._apply_persisted_results({}, {"a", "b"})
    assert not dlg._hidden_uuids


def test_late_load_cannot_restore_repaired_station(dialog):
    dlg, _ = dialog
    dlg._apply_recheck(HealthResult(uuid="fixed", stream_ok=True))
    dlg._apply_persisted_results({"fixed": problem("fixed"), "old": problem("old")}, set())
    wait_for(lambda: displayed(dlg) == ["old"])
    assert "fixed" not in dlg._results


def test_slow_save_does_not_block_ui_and_finishes_after_close(dialog):
    dlg, db = dialog
    entered, release = threading.Event(), threading.Event()
    save = db.record_health_results
    def blocked_save(rows):
        entered.set()
        assert release.wait(5)
        save(rows)
    with patch.object(db, "record_health_results", blocked_save):
        try:
            dlg._apply_recheck(HealthResult(uuid="saved", stream_ok=False))
            wait_for(entered.is_set)
            wait_for(lambda: displayed(dlg) == ["saved"])
            dlg.Destroy()
            wx.Yield()
        finally:
            release.set()
        dlg._save_thread.join(5)
    assert [row["uuid"] for row in db.health_results()] == ["saved"]


def test_failed_save_reports_error_and_worker_can_continue(dialog):
    dlg, db = dialog
    with patch.object(db, "record_health_results", side_effect=OSError("disk full")), \
            patch("radiomaster.ui.station_health_dialog.wx.MessageBox") as message:
        dlg._apply_recheck(HealthResult(uuid="failed", stream_ok=False))
        wait_for(lambda: message.called)
        assert "disk full" in message.call_args.args[0]
        wait_for(lambda: not dlg._save_jobs.unfinished_tasks)
    dlg._apply_recheck(HealthResult(uuid="retry", stream_ok=False))
    wait_for(lambda: not dlg._save_jobs.unfinished_tasks)
    assert [row["uuid"] for row in db.health_results()] == ["retry"]


def test_saved_name_and_website_problems_survive_reload(dialog):
    dlg, db = dialog
    db.record_health_results([
        HealthResult(uuid="name", stream_ok=True, name_ok=False).to_row(),
        HealthResult(uuid="website", stream_ok=True, website_ok=False).to_row(),
        HealthResult(uuid="unknown", stream_ok=True).to_row(),
    ])
    dlg._load_persisted_async()
    wait_for(lambda: set(displayed(dlg)) == {"name", "website"})


def test_failed_hide_keeps_results_and_allows_retry(dialog):
    dlg, db = dialog
    dlg._results = {"a": problem("a"), "b": problem("b")}
    dlg._refresh_results()
    wait_for(lambda: len(displayed(dlg)) == 2)
    with patch.object(db, "hide_stations", side_effect=OSError("database unavailable")), \
            patch("radiomaster.ui.station_health_dialog.wx.MessageBox", return_value=wx.YES) as message:
        dlg._on_hide_all_dead(None)
        wait_for(lambda: not dlg._hiding)
        assert "database unavailable" in message.call_args.args[0]
    assert len(displayed(dlg)) == 2
    assert not db.hidden_uuids()
    assert dlg._btn_hide_dead.IsEnabled()
    with patch("radiomaster.ui.station_health_dialog.wx.MessageBox", return_value=wx.YES):
        dlg._on_hide_all_dead(None)
        wait_for(lambda: not displayed(dlg))
    assert db.hidden_uuids() == {"a", "b"}


def test_completion_waits_for_queued_save_and_closed_dialog_rejects_updates(dialog):
    dlg, _ = dialog
    entered, release = threading.Event(), threading.Event()
    def save(rows):
        entered.set()
        assert release.wait(5)
    with patch.object(dlg._db, "record_health_results", save), \
            patch.object(dlg._service, "is_finished", return_value=True), \
            patch.object(dlg, "_announce_completion") as complete:
        try:
            dlg._apply_recheck(HealthResult(uuid="pending", stream_ok=False))
            wait_for(entered.is_set)
            dlg._on_drain_timer(None)
            complete.assert_not_called()
        finally:
            release.set()
        wait_for(lambda: not dlg._save_jobs.unfinished_tasks)
        dlg._on_drain_timer(None)
        complete.assert_called_once()
    dlg.Destroy()
    dlg._apply_recheck(HealthResult(uuid="too-late", stream_ok=False))
    assert "too-late" not in dlg._results
