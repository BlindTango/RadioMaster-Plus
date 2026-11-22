"""Settings > Network > Identify as: Chrome, Firefox or custom, used by every network call
including the radio player."""

import gc
import http.server
import os
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest
import wx

from radiomaster.utils import network
from radiomaster.utils.config import ConfigManager


@pytest.fixture
def config(tmp_path, monkeypatch):
    cfg = ConfigManager(str(tmp_path))
    monkeypatch.setattr(ConfigManager, "_instance", cfg)
    return cfg


def test_default_is_the_applications_own_agent(config):
    assert network.user_agent_override() == ""
    assert network.get_user_agent("fallback").startswith("RadioMaster+/")


@pytest.mark.parametrize("preset,needle", [("chrome", "Chrome/"), ("firefox", "Firefox/")])
def test_browser_presets(config, preset, needle):
    config.set("network.user_agent_preset", value=preset)
    config.set("network.user_agent", value="ignored when a preset is chosen")
    agent = network.get_user_agent("fallback")
    assert agent.startswith("Mozilla/5.0") and needle in agent
    assert network.user_agent_override() == agent


def test_custom_text_is_used_only_when_custom_is_chosen(config):
    config.set("network.user_agent", value="MyPlayer/9")
    assert network.user_agent_override() == "MyPlayer/9"          # saved before presets existed
    config.set("network.user_agent_preset", value="custom")
    assert network.get_user_agent("x") == "MyPlayer/9"
    config.set("network.user_agent_preset", value="default")
    assert network.user_agent_override() == "" and network.get_user_agent("x").startswith("RadioMaster+/")


def test_blank_custom_text_falls_back_to_the_default(config):
    config.set("network.user_agent_preset", value="custom")
    config.set("network.user_agent", value="   ")
    assert network.get_user_agent("x").startswith("RadioMaster+/")


def test_every_http_client_reads_the_same_choice(config):
    config.set("network.user_agent_preset", value="firefox")
    assert network.get_user_agent("a") == network.get_user_agent("b") == network.USER_AGENT_PRESETS["firefox"][1]
    assert network.USER_AGENT_PRESETS["firefox"][1] in network.get_ffmpeg_input_args()


def test_radio_play_command_carries_the_chosen_agent(config, monkeypatch):
    from radiomaster.engine import bass_radio_engine
    config.set("network.user_agent_preset", value="chrome")
    assert "Chrome/" in bass_radio_engine._chosen_user_agent()
    config.set("network.user_agent_preset", value="default")
    assert bass_radio_engine._chosen_user_agent() == ""


def test_network_settings_choice_saves_and_reloads(config):
    from radiomaster.ui.settings_dialog import NetworkPanel
    gc.collect()
    app = wx.App(False)
    frame = wx.Frame(None)
    panel = NetworkPanel(frame, config)
    assert panel.ua_choice.GetSelection() == 0 and not panel.user_agent_txt.IsEnabled()
    panel.ua_choice.SetSelection(panel._ua_keys.index("firefox"))
    panel._update_ua_states()
    panel.onSave()
    assert config.get("network.user_agent_preset") == "firefox"
    reopened = NetworkPanel(frame, config)
    assert reopened._ua_keys[reopened.ua_choice.GetSelection()] == "firefox"
    reopened.ua_choice.SetSelection(reopened._ua_keys.index("custom"))
    reopened._update_ua_states()
    assert reopened.user_agent_txt.IsEnabled()
    frame.Destroy()
    assert app


def test_a_setting_saved_before_presets_opens_as_custom(config):
    from radiomaster.ui.settings_dialog import NetworkPanel
    gc.collect()
    app = wx.App(False)
    config.set("network.user_agent", value="Old/1")
    frame = wx.Frame(None)
    panel = NetworkPanel(frame, config)
    assert panel._ua_keys[panel.ua_choice.GetSelection()] == "custom" and panel.user_agent_txt.GetValue() == "Old/1"
    frame.Destroy()
    assert app


def test_bass_sends_the_chosen_agent_and_goes_back_to_its_own(tmp_path):
    """Real BASS against a local server that records the User-Agent header it receives."""
    from radiomaster.engine import bass_host
    from radiomaster.utils.tools import get_ffmpeg, get_tools_dir
    if not os.path.isfile(os.path.join(get_tools_dir(), "bass", "x64", "bass.dll")):
        pytest.skip("BASS is not bundled")
    mp3 = tmp_path / "t.mp3"
    subprocess.run([get_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=15", "-c:a", "libmp3lame", str(mp3)],
                   check=True, timeout=60)
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            seen.append(self.headers.get("User-Agent"))
            data = mp3.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/live.mp3"
    host = bass_host.BassHost(str(get_tools_dir()))
    ok, why = host.load()
    if not ok:
        server.shutdown()
        pytest.skip(f"BASS could not start here: {why}")
    agent = network.USER_AGENT_PRESETS["chrome"][1]
    try:
        results = []
        for label, ua in (("custom", agent), ("default", "")):
            seen.clear()
            host.set_user_agent(ua)
            assert host.play(url, 1.0, seq=len(results) + 1, seekable=False)[0]
            time.sleep(0.5)
            host.stop()
            results.append((label, seen[:1]))
        assert results[0][1] == [agent]
        assert results[1][1] and results[1][1][0].startswith("BASS/")
    finally:
        server.shutdown()
