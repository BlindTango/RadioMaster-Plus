"""The whole application started in Spanish: menus, tabs and dialogs."""

import gc

import pytest
import wx

from radiomaster.app import RadioMasterApp
from radiomaster.services.station_api import Station


@pytest.fixture
def spanish_window(tmp_path, monkeypatch):
    from radiomaster.utils.config import ConfigManager

    paths = {name: str(tmp_path / name) for name in (
        "config", "data", "cache", "downloads", "recordings", "logs",
    )}
    # Patch imported aliases before the source function so importing a
    # previously unloaded module cannot retain a temporary test closure.
    monkeypatch.setattr("radiomaster.ui.settings_dialog.get_paths", lambda: paths)
    monkeypatch.setattr("radiomaster.services.station_db.get_paths", lambda: paths)
    monkeypatch.setattr("radiomaster.app.get_paths", lambda: paths)
    monkeypatch.setattr("radiomaster.utils.paths.get_paths", lambda: paths)
    monkeypatch.setattr(ConfigManager, "_instance", ConfigManager._instance)
    config = ConfigManager(paths["config"])
    config.set("updates.check_on_startup", value=False)
    config.set("updates.ytdlp_auto_update", value=False)
    config.set("radio.station_update_frequency", value="off")
    # First-run wizard must not pop up mid-test (its deferred CallAfter
    # would fire after the window is torn down).
    config.set("general.first_run_complete", value=True)
    config.set("general.language", value="es")
    config.save()
    # Network discovery is not part of a keyboard/focus check.
    monkeypatch.setattr("radiomaster.services.station_api._discover_servers", lambda: [])
    monkeypatch.setattr("radiomaster.services.station_api.StationAPI.bulk_stations",
                        lambda *args, **kwargs: [])
    # Earlier test modules leave wx.App objects behind for the garbage collector.
    # If one is collected while this app is starting, wx's global app pointer is
    # cleared mid-OnInit ("No wx.App created yet"), so collect them first.
    import gc
    gc.collect()
    app = RadioMasterApp()
    # wx.LogGui opens modal error windows when queued native warnings flush at
    # shutdown. Keep diagnostics in pytest's stderr instead of blocking teardown.
    wx.Log.SetActiveTarget(wx.LogStderr())
    win = app._main_window
    # First/Previous/Next/Last are correctly greyed out (and therefore
    # Tab-skipped) until there's station history to navigate -- exactly
    # what a fresh app start looks like. These tab-order tests care about
    # the *order*, not button-enabled-state (that's covered separately in
    # test_playback_engine.py's history tests), so give the transport bar
    # some history up front to put it in its normal, fully-focusable state.
    win._radio_panel._push_history(Station(uuid="a", name="A", url="http://a"))
    win._radio_panel._push_history(Station(uuid="b", name="B", url="http://b"))
    win._radio_panel._push_history(Station(uuid="c", name="C", url="http://c"))
    win._radio_panel._history_index = 1  # middle: both Previous and Next have somewhere to go
    win._update_transport_button_states()
    try:
        yield app, win
    finally:
        from radiomaster.i18n import I18nManager
        I18nManager().set_language("en")
        win._lyrics_timer.Stop()
        win._station_update_scheduler.shutdown()
        win._health_service.stop()
        win._global_hotkey_manager.unregister_all()
        app.OnExit()
        win.Destroy()



def test_menus_and_tabs_are_spanish(spanish_window):
    _app, win = spanish_window
    bar = win.GetMenuBar()
    menus = [bar.GetMenuLabelText(i) for i in range(bar.GetMenuCount())]
    assert menus[:2] == ["Archivo", "Ver"]
    assert "Ayuda" in menus and "Herramientas" in menus
    help_menu = bar.GetMenu(bar.FindMenu("Ayuda"))
    labels = [i.GetItemLabelText() for i in help_menu.GetMenuItems() if not i.IsSeparator()]
    assert labels[0] == "Manual de usuario" and labels[-1] == "Acerca de RadioMaster+"
    tabs = [win._listbook.GetPageText(i) for i in range(win._listbook.GetPageCount())]
    assert tabs[:3] == ["Radio", "Podcasts", "Audiolibros"]
    assert "Reproductor multimedia" in tabs


def test_shortcut_hints_survive_translation(spanish_window):
    _app, win = spanish_window
    bar = win.GetMenuBar()
    file_menu = bar.GetMenu(bar.FindMenu("Archivo"))
    labels = [i.GetItemLabel() for i in file_menu.GetMenuItems() if not i.IsSeparator()]
    assert any(label.startswith("&Abrir archivo...") and "	" in label for label in labels)


def test_dialogs_open_in_spanish(spanish_window):
    app, win = spanish_window
    from radiomaster.ui.sleep_timer_dialog import SleepTimerDialog
    dlg = SleepTimerDialog(win, on_start=lambda m, mode: None, on_stop=lambda: None,
                           is_active=False, remaining=0)
    try:
        texts = [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, (wx.StaticText, wx.Button))]
        assert "Iniciar temporizador" in texts and "Duración (minutos):" in texts
    finally:
        dlg.Destroy()


@pytest.mark.parametrize("lang,file_menu", [("ja", "ファイル"), ("ru", "Файл"), ("de", "Datei")])
def test_other_languages_start_and_translate_the_menu_bar(tmp_path, monkeypatch, lang, file_menu):
    import gc
    from radiomaster.i18n import I18nManager
    from radiomaster.utils.config import ConfigManager
    paths = {name: str(tmp_path / name) for name in (
        "config", "data", "cache", "downloads", "recordings", "logs")}
    monkeypatch.setattr("radiomaster.ui.settings_dialog.get_paths", lambda: paths)
    monkeypatch.setattr("radiomaster.services.station_db.get_paths", lambda: paths)
    monkeypatch.setattr("radiomaster.app.get_paths", lambda: paths)
    monkeypatch.setattr("radiomaster.utils.paths.get_paths", lambda: paths)
    monkeypatch.setattr(ConfigManager, "_instance", ConfigManager._instance)
    config = ConfigManager(paths["config"])
    for key, value in (("updates.check_on_startup", False), ("updates.ytdlp_auto_update", False),
                       ("radio.station_update_frequency", "off"),
                       ("general.first_run_complete", True), ("general.language", lang)):
        config.set(key, value=value)
    config.save()
    monkeypatch.setattr("radiomaster.services.station_api._discover_servers", lambda: [])
    monkeypatch.setattr("radiomaster.services.station_api.StationAPI.bulk_stations",
                        lambda *args, **kwargs: [])
    gc.collect()
    app = RadioMasterApp()
    win = app._main_window
    try:
        bar = win.GetMenuBar()
        assert bar.GetMenuLabelText(0).startswith(file_menu)
        assert bar.GetMenuCount() >= 5
    finally:
        I18nManager().set_language("en")
        win._lyrics_timer.Stop()
        win._station_update_scheduler.shutdown()
        win._health_service.stop()
        win._global_hotkey_manager.unregister_all()
        app.OnExit()
        win.Destroy()
