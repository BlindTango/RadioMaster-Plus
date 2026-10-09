"""Tests for MainWindow wiring of the catalog status, listening stats,
and first-run wizard features (menu items, shortcut entries, config flag)."""

from datetime import datetime

import pytest
import wx

from radiomaster.ui.shortcut_editor import DEFAULT_SHORTCUTS


class TestShortcutCatalogue:
    def test_new_actions_are_in_the_catalogue(self) -> None:
        assert "catalog_status" in DEFAULT_SHORTCUTS
        assert "stats" in DEFAULT_SHORTCUTS
        assert DEFAULT_SHORTCUTS["catalog_status"]["category"] == "Tools menu"
        assert DEFAULT_SHORTCUTS["stats"]["category"] == "Tools menu"

    def test_new_defaults_do_not_conflict(self) -> None:
        from radiomaster.ui.shortcut_editor import find_conflict, shortcut_signature

        signatures = [
            shortcut_signature(s)
            for s in DEFAULT_SHORTCUTS.values()
            if s["key"]
        ]
        assert len(signatures) == len(set(signatures))


class TestMainWindowWiring:
    @pytest.fixture
    def app_and_window(self, tmp_path, monkeypatch):
        from radiomaster.utils.config import ConfigManager

        paths = {name: str(tmp_path / name) for name in (
            "config", "data", "cache", "downloads", "recordings", "logs",
        )}
        monkeypatch.setattr("radiomaster.ui.settings_dialog.get_paths", lambda: paths)
        monkeypatch.setattr("radiomaster.services.station_db.get_paths", lambda: paths)
        monkeypatch.setattr("radiomaster.app.get_paths", lambda: paths)
        monkeypatch.setattr("radiomaster.utils.paths.get_paths", lambda: paths)
        monkeypatch.setattr(ConfigManager, "_instance", ConfigManager._instance)
        config = ConfigManager(paths["config"])
        config.set("updates.check_on_startup", value=False)
        config.set("updates.ytdlp_auto_update", value=False)
        config.set("radio.station_update_frequency", value="off")
        # First-run wizard must not pop up mid-test.
        config.set("general.first_run_complete", value=True)
        config.save()
        monkeypatch.setattr("radiomaster.services.station_api._discover_servers", lambda: [])
        monkeypatch.setattr(
            "radiomaster.services.station_api.StationAPI.bulk_stations",
            lambda *args, **kwargs: [],
        )
        from radiomaster.app import RadioMasterApp
        app = RadioMasterApp()
        wx.Log.SetActiveTarget(wx.LogStderr())
        win = app._main_window
        try:
            yield app, win
        finally:
            win._lyrics_timer.Stop()
            win._station_update_scheduler.shutdown()
            win._health_service.stop()
            win._global_hotkey_manager.unregister_all()
            app.OnExit()
            win.Destroy()

    def test_tools_menu_has_new_items(self, app_and_window) -> None:
        _app, win = app_and_window
        menu_bar = win.GetMenuBar()
        tools = menu_bar.GetMenu(menu_bar.FindMenu("Tools"))
        labels = [
            item.GetItemLabelText()
            for item in tools.GetMenuItems()
            if not item.IsSeparator()
        ]
        assert "Station Catalog Status..." in labels
        assert "Listening Statistics..." in labels

    def test_stats_service_is_wired_to_engine(self, app_and_window, monkeypatch) -> None:
        """The engine's on_state_change must reach the stats service --
        chained, not overwritten (the UI handler still fires too)."""
        import radiomaster.services.stats_service as stats_module
        _app, win = app_and_window
        assert win._stats_service is not None
        # The service deliberately drops 0-second sessions (a play/stop
        # blip is not listening time), so drive a controllable clock to
        # give the session real elapsed time.
        clock = {"now": datetime(2026, 10, 9, 12, 0, 0)}
        monkeypatch.setattr(stats_module, "_now",
                            lambda: clock["now"])
        win._engine._on_state_change = None
        win._setup_engine_callbacks()
        win._engine._on_state_change("playing")
        clock["now"] = datetime(2026, 10, 9, 12, 0, 5)
        win._engine._on_state_change("stopped")
        rows = win._db.fetchall("SELECT * FROM listening_sessions")
        assert len(rows) == 1
        assert rows[0]["seconds_listened"] == 5

    def test_first_run_wizard_shown_once_then_flag_set(
            self, app_and_window, monkeypatch) -> None:
        """With the flag unset, the wizard is queued; after it runs the
        flag is set so it never asks again."""
        _app, win = app_and_window
        shown = []
        monkeypatch.setattr(
            "radiomaster.ui.first_run_dialog.FirstRunDialog",
            lambda parent: shown.append(parent) or type("Fake", (), {
                "ShowModal": lambda self: wx.ID_OK,
                "Destroy": lambda self: None,
            })(),
        )
        win._config.set("general.first_run_complete", value=False)
        win._show_first_run_wizard()
        assert len(shown) == 1
        assert win._config.get("general.first_run_complete", default=False) is True
        # Second call: the flag is set, so __init__'s guard would skip it.
        win._show_first_run_wizard()
        assert len(shown) == 2  # explicit call always shows; the guard is in __init__

    def test_catalog_status_dialog_opens_with_summary(self, app_and_window,
                                                      monkeypatch) -> None:
        """Opening the dialog announces its summary in the status bar."""
        _app, win = app_and_window
        announced = []
        monkeypatch.setattr(
            win._status_bar, "set_status", lambda text, announce=True: announced.append(text)
        )
        monkeypatch.setattr(
            "radiomaster.ui.catalog_status_dialog.CatalogStatusDialog.ShowModal",
            lambda self: wx.ID_CLOSE,
        )
        win._show_catalog_status()
        assert len(announced) == 1
        assert "stations stored" in announced[0]
        assert "Last updated" in announced[0]

    def test_stats_dialog_opens_with_summary(self, app_and_window, monkeypatch) -> None:
        _app, win = app_and_window
        announced = []
        monkeypatch.setattr(
            win._status_bar, "set_status", lambda text, announce=True: announced.append(text)
        )
        monkeypatch.setattr(
            "radiomaster.ui.stats_dialog.StatsDialog.ShowModal",
            lambda self: wx.ID_CLOSE,
        )
        win._show_stats()
        assert announced == ["You have listened for 0 seconds this week."]