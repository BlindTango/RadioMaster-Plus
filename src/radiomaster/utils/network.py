"""Shared network settings (proxy, timeout, user agent) for HTTP-using services.

Every service in this app built its own requests.Session/requests.get calls
independently, so the Network settings panel (proxy, timeout, user agent)
had nowhere to actually take effect. This centralizes reading those settings
so services apply them consistently instead of each hardcoding its own
values.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def _config():
    from radiomaster.utils.config import ConfigManager
    return ConfigManager.get_instance()


def get_timeout(default: float = 10.0) -> float:
    """Configured HTTP timeout in seconds, falling back to *default*."""
    config = _config()
    return float(config.get("network.timeout", default=default) or default)


def get_proxies() -> dict[str, str] | None:
    """requests-style proxies dict, or None if proxying is disabled/unset."""
    config = _config()
    if not config.get("network.proxy_enabled", default=False):
        return None
    host = config.get("network.proxy_host", default="").strip()
    if not host:
        return None
    port = int(config.get("network.proxy_port", default=8080))
    candidate = host if "://" in host else f"http://{host}"
    parsed = urlsplit(candidate)
    hostname = parsed.hostname
    if not hostname:
        return None
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "http"
    try:
        parsed_port = parsed.port
    except ValueError:
        return None
    if parsed_port is not None:
        netloc = parsed.netloc
    else:
        credentials = ""
        if parsed.username:
            credentials = parsed.username
            if parsed.password:
                credentials += f":{parsed.password}"
            credentials += "@"
        netloc = f"{credentials}{hostname}:{port}"
    proxy_url = urlunsplit((scheme, netloc, "", "", ""))
    return {"http": proxy_url, "https": proxy_url}


def get_user_agent(fallback: str) -> str:
    """Configured User-Agent override, or *fallback* (the app's own
    identifying UA) if the user hasn't set one."""
    config = _config()
    value = config.get("network.user_agent", default="").strip()
    if value:
        return value
    try:
        from radiomaster import __app_name__, __version__
        return f"{__app_name__}/{__version__}"
    except ImportError:
        return fallback


def get_yt_dlp_proxy_args() -> list[str]:
    """Network arguments for a yt-dlp command line."""
    args = [
        "--socket-timeout", str(get_timeout(default=10)),
        "--user-agent", get_user_agent("RadioMaster+/1.0"),
    ]
    proxies = get_proxies()
    if proxies:
        args.extend(["--proxy", proxies["http"]])
    return args


def get_ffmpeg_input_args(user_agent_fallback: str = "RadioMaster+/1.0") -> list[str]:
    """FFmpeg/FFplay input options for HTTP timeout and User-Agent.

    These options must be placed before the input URL. Proxy routing is
    supplied separately through :func:`get_ffplay_http_proxy_env` because
    FFmpeg's HTTP handlers read the conventional proxy environment variables.
    """
    return [
        "-rw_timeout", str(int(get_timeout(default=10) * 1_000_000)),
        "-user_agent", get_user_agent(user_agent_fallback),
    ]


def get_ffplay_http_proxy_env() -> dict[str, str]:
    """Extra environment variables to make ffplay/ffmpeg route HTTP(S)
    through the configured proxy (ffmpeg's http/https protocol handlers
    read these standard env vars directly)."""
    proxies = get_proxies()
    if not proxies:
        return {}
    return {"http_proxy": proxies["http"], "https_proxy": proxies.get("https", proxies["http"])}


def apply_to_session(session: Any, user_agent_fallback: str) -> None:
    """Apply proxy + user-agent settings to a requests.Session in place."""
    session.headers["User-Agent"] = get_user_agent(user_agent_fallback)
    proxies = get_proxies()
    if proxies:
        session.proxies.update(proxies)
    else:
        session.proxies.clear()


def request_kwargs(user_agent_fallback: str, timeout_default: float = 10.0) -> dict[str, Any]:
    """Common keyword arguments for one-off ``requests`` calls."""
    kwargs: dict[str, Any] = {
        "timeout": get_timeout(default=timeout_default),
        "headers": {"User-Agent": get_user_agent(user_agent_fallback)},
    }
    proxies = get_proxies()
    if proxies:
        kwargs["proxies"] = proxies
    return kwargs
