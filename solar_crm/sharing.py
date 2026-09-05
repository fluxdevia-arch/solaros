from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _normalized_url(value: str | None) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    if not parts.hostname:
        return ""
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path.rstrip("/"), "", ""))


def _is_public(value: str) -> bool:
    hostname = (urlsplit(value).hostname or "").lower()
    return bool(hostname and hostname not in LOCAL_HOSTS)


def _browser_app_base(current_url: str) -> str:
    """Derive the app base, removing the two public field-page routes."""
    normalized = _normalized_url(current_url)
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    path = parts.path.rstrip("/")
    for route in ("/inspections", "/service-orders"):
        if path.endswith(route):
            path = path[: -len(route)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def resolve_share_base_url(configured_url: str | None, current_url: str | None) -> str:
    """Prefer the real public browser host over a stale localhost setting."""
    configured = _normalized_url(configured_url)
    browser_base = _browser_app_base(str(current_url or ""))

    if _is_public(browser_base):
        if _is_public(configured):
            configured_host = (urlsplit(configured).hostname or "").lower()
            browser_host = (urlsplit(browser_base).hostname or "").lower()
            if configured_host == browser_host:
                return configured.rstrip("/")
        return browser_base
    if _is_public(configured):
        return configured.rstrip("/")
    return browser_base or configured or "http://localhost:8501"
