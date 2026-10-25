"""Regression tests for the gaps closed after the v1.2.3 audit."""

import time

from radiomaster.i18n import LANGUAGES
from radiomaster.services.lyrics_service import LyricsService
from radiomaster.services.sleep_timer import SleepTimer
from radiomaster.utils.playlists import read_playlist


def _wait_idle(timer, limit=5.0):
    end = time.time() + limit
    while timer.is_active and time.time() < end:
        time.sleep(0.05)


def test_end_of_track_arms_instead_of_stopping(monkeypatch):
    monkeypatch.setattr("radiomaster.services.sleep_timer.time.sleep", lambda s: None)
    timer = SleepTimer()
    stopped, armed = [], []
    timer.on_timeout(lambda: stopped.append(1))
    timer.on_mode_action(lambda: armed.append(1))
    timer.start(1 / 60, "end_of_track")  # one second
    _wait_idle(timer)
    assert armed == [1]
    assert stopped == []
    assert timer.pending_mode == "end_of_track"
    timer.complete_pending()
    assert timer.pending_mode is None


def test_countdown_still_stops_immediately(monkeypatch):
    monkeypatch.setattr("radiomaster.services.sleep_timer.time.sleep", lambda s: None)
    timer = SleepTimer()
    stopped = []
    timer.on_timeout(lambda: stopped.append(1))
    timer.start(1 / 60, "countdown")
    _wait_idle(timer)
    assert stopped == [1]
    assert timer.pending_mode is None


def test_stopping_the_timer_clears_a_pending_stop(monkeypatch):
    monkeypatch.setattr("radiomaster.services.sleep_timer.time.sleep", lambda s: None)
    timer = SleepTimer()
    timer.start(1 / 60, "end_of_playlist")
    _wait_idle(timer)
    assert timer.pending_mode == "end_of_playlist"
    timer.stop()
    assert timer.pending_mode is None


def test_m3u_relative_and_url_entries(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    pl = tmp_path / "list.m3u"
    pl.write_text("#EXTM3U\n#EXTINF:1,a\na.mp3\nhttp://example.com/s\n", encoding="utf-8")
    entries = read_playlist(str(pl))
    assert entries == [str(tmp_path / "a.mp3"), "http://example.com/s"]


def test_pls_entries_in_numeric_order(tmp_path):
    pl = tmp_path / "list.pls"
    pl.write_text("[playlist]\nFile10=http://x/10\nFile2=http://x/2\nFile1=http://x/1\n"
                  "NumberOfEntries=3\n", encoding="utf-8")
    assert read_playlist(str(pl)) == ["http://x/1", "http://x/2", "http://x/10"]


def test_genius_modern_markup_is_parsed():
    page = ('<div data-lyrics-container="true" class="x">Line one<br/>Line &amp; two</div>'
            '<div data-lyrics-container="true">Verse two<br/>end</div>')
    text = LyricsService._extract_genius_lyrics(page)
    assert text == "Line one\nLine & two\nVerse two\nend"


def test_genius_legacy_markup_still_works():
    page = '<div class="lyrics"><p>Old<br>layout</p></div>'
    assert "Old" in LyricsService._extract_genius_lyrics(page)


def test_gpodder_upload_sends_plain_list(monkeypatch):
    from radiomaster.services.gpodder_sync import GpodderSync
    sent = {}

    class Resp:
        status_code = 200

    sync = GpodderSync("u", "p")
    monkeypatch.setattr(sync._session, "put",
                        lambda url, json=None, timeout=None: sent.update(body=json) or Resp())
    assert sync.upload_subscriptions(["http://a/feed"])
    assert sent["body"] == ["http://a/feed"]


def test_language_list_only_offers_available_catalogues():
    assert "en" in LANGUAGES
    assert set(LANGUAGES) == {"en"}


def test_m3u_round_trip_keeps_relative_paths_and_urls(tmp_path):
    from radiomaster.utils.playlists import write_m3u
    media = tmp_path / "music"
    media.mkdir()
    song = media / "a.mp3"
    song.write_bytes(b"x")
    target = tmp_path / "out.m3u8"
    write_m3u(str(target), [str(song), "http://example.com/s"], ["Song A", "Stream"])
    text = target.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "#EXTM3U"
    import os
    assert os.path.join("music", "a.mp3") in text
    assert read_playlist(str(target)) == [str(song), "http://example.com/s"]


def test_dynamic_range_converts_db_threshold_for_the_compressor():
    from radiomaster.engine.bass_radio_engine import BassRadioEngine
    sent = []
    engine = BassRadioEngine.__new__(BassRadioEngine)
    engine._rate = 1.0
    engine._request = lambda msg: sent.append(msg) or {}
    engine.set_rate = lambda r: None
    effects = {"dynamic_range": {"enabled": True,
                                 "params": {"threshold": -20, "ratio": 8, "attack": 5, "release": 50}}}
    engine.apply_effects(effects)
    fx = next(m for m in sent if m.get("cmd") == "set_fx")
    assert fx["fx"] == ["compressor"]
    assert abs(fx["params"]["compressor"]["threshold"] - 0.1) < 1e-9
    assert fx["params"]["compressor"]["ratio"] == 8


def test_equalizer_uses_one_filter_per_band():
    from radiomaster.engine.bass_radio_engine import BassRadioEngine
    sent = []
    engine = BassRadioEngine.__new__(BassRadioEngine)
    engine._rate = 1.0
    engine._request = lambda msg: sent.append(msg) or {}
    engine.set_rate = lambda r: None
    engine.apply_effects({"equalizer": {"enabled": True, "params": {"32": 4, "64": 2, "1k": -3}}})
    gains = {m["band"]: m["gain_db"] for m in sent if m.get("cmd") == "set_eq_gain"}
    assert len(gains) == 9
    assert gains["eqb_80"] == 3 and gains["eqb_1k"] == -3 and gains["eqb_16k"] == 0


def test_onecore_engine_is_offered_and_wired_like_sapi():
    from radiomaster.services.audiobook_tts import TTS_ENGINES, create_tts, configure_tts
    from radiomaster.services.onecore_tts import winrt_available
    if not winrt_available():
        return
    assert "onecore" in TTS_ENGINES
    engine = create_tts("onecore")
    voices = engine.get_voices()
    assert voices and {"id", "name"} <= set(voices[0])
    configure_tts(engine, voices[0]["id"], 3, 50)
    assert engine._rate == 3 and engine._volume == 50
