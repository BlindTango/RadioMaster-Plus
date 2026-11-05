"""Stream failures must survive subsequent successful BASS config calls."""

from unittest.mock import Mock, patch

from radiomaster.engine.bass_host import BassHost, _ssl_verify_bypass_hosts


def test_http_open_reports_original_error_after_config_restore():
    host = BassHost("unused")
    error = [0]
    host._dll = Mock()

    def create(*args):
        error[0] = 40
        return 0

    def configure(*args):
        error[0] = 0
        return True

    host._dll.BASS_StreamCreateURL.side_effect = create
    host._dll.BASS_SetConfig.side_effect = configure
    host._dll.BASS_GetConfig.return_value = 1
    host._dll.BASS_ErrorGetCode.side_effect = lambda: error[0]
    with patch("radiomaster.engine.bass_host.urllib.request.urlopen", side_effect=OSError), \
            patch("radiomaster.engine.bass_host._resolve_playlist_url", return_value=None):
        ok, message = host.play("http://example.test/live", seq=1)
    assert not ok
    assert "BASS error 40" in message
    assert "timed out" in message
    assert error[0] == 0


def test_format_error_does_not_trigger_ssl_retry():
    host = BassHost("unused")
    host._dll = Mock()
    host._dll.BASS_ErrorGetCode.return_value = 41
    create = Mock(return_value=0)
    assert host._stream_create_url_with_ssl_fallback(True, "example.test", create) == 0
    create.assert_called_once()
    host._dll.BASS_SetConfig.assert_not_called()
    assert host._last_stream_error == 41


def test_ssl_retry_preserves_failure_before_restoring_config():
    host = BassHost("unused")
    host._dll = Mock()
    host._dll.BASS_ErrorGetCode.side_effect = [10, 10, 2]
    create = Mock(return_value=0)
    try:
        assert host._stream_create_url_with_ssl_fallback(True, "example.test", create) == 0
        assert create.call_count == 2
        assert host._last_stream_error == 2
    finally:
        _ssl_verify_bypass_hosts.discard("example.test")
