"""Shared network settings (proxy, timeout, user agent) for HTTP-using services.

Every service in this app built its own requests.Session/requests.get calls
independently, so the Network settings panel (proxy, timeout, user agent)
had nowhere to actually take effect. This centralizes reading those settings
so services apply them consistently instead of each hardcoding its own
values.
"""

from __future__ import annotations

from typing import Any


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
    port = config.get("network.proxy_port", default=8080)
    proxy_url = f"http://{host}:{port}"
    return {"http": proxy_url, "https": proxy_url}


def get_user_agent(fallback: str) -> str:
    """Configured User-Agent override, or *fallback* (the app's own
    identifying UA) if the user hasn't set one."""
    config = _config()
    value = config.get("network.user_agent", default="").strip()
    return value or fallback


def get_yt_dlp_proxy_args() -> list[str]:
    """--proxy args for a yt-dlp command line, or [] if not configured."""
    proxies = get_proxies()
    if not proxies:
        return []
    return ["--proxy", proxies["http"]]


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
