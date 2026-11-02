"""Shared HTTP helpers: on-disk cache, retry with backoff, SHA-256 recording,
GitHub rate-limit handling, and per-host throttling.

The GitHub token is read from the GITHUB_TOKEN env var and is never printed,
logged, or written to the cache (only response bodies and selected headers are
cached).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache" / "http"
DOWNLOAD_DIR = ROOT / "data" / "raw"

USER_AGENT = "pilot-research-script (academic, contact via GitHub)"

# Minimum seconds between requests, per host.
MIN_INTERVAL = {
    "f-droid.org": 1.0,
    "api.github.com": 0.0,
    "raw.githubusercontent.com": 0.2,
    "gitlab.com": 0.5,
    "api.semanticscholar.org": 3.0,
}
_last_request: dict[str, float] = {}

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _cache_key(url: str, params: dict | None) -> str:
    raw = url + "?" + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _throttle(host: str) -> None:
    interval = MIN_INTERVAL.get(host, 0.5)
    wait = _last_request.get(host, 0.0) + interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request[host] = time.monotonic()


def _auth_headers(host: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if token and host == "api.github.com":
        return {"Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}
    return {}


def _respect_github_rate_limit(resp: requests.Response) -> None:
    remaining = resp.headers.get("X-RateLimit-Remaining")
    reset = resp.headers.get("X-RateLimit-Reset")
    if remaining is None or reset is None:
        return
    if int(remaining) < 50:
        sleep_for = max(0, int(reset) - int(time.time())) + 5
        print(f"[http] GitHub rate limit low ({remaining} left); sleeping {sleep_for}s")
        time.sleep(sleep_for)


def _request(url: str, params: dict | None, stream: bool, retries: int) -> requests.Response:
    host = urlparse(url).netloc
    for attempt in range(retries):
        _throttle(host)
        try:
            resp = _session.get(url, params=params, headers=_auth_headers(host),
                                timeout=60, stream=stream)
        except requests.RequestException as exc:
            err = exc
        else:
            if host == "api.github.com":
                _respect_github_rate_limit(resp)
            if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                continue  # rate-limit sleep already happened; retry
            if resp.status_code in (429, 500, 502, 503, 504):
                err = RuntimeError(f"HTTP {resp.status_code}")
            else:
                return resp
        backoff = 2 ** attempt
        print(f"[http] {url} failed ({err}); retry {attempt + 1}/{retries} in {backoff}s")
        time.sleep(backoff)
    raise RuntimeError(f"giving up on {url} after {retries} attempts")


def get(url: str, params: dict | None = None, retries: int = 5) -> dict:
    """GET with on-disk cache. Returns {status, headers, text, fetched_at}.

    Non-2xx responses (e.g. 404) are cached too, so negative lookups are not
    repeated.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(url, params)}.json"
    if path.exists():
        return json.loads(path.read_text())
    resp = _request(url, params, stream=False, retries=retries)
    keep = {k: v for k, v in resp.headers.items()
            if k.lower() in ("content-type", "etag", "last-modified", "date", "link")}
    entry = {"url": url, "params": params, "status": resp.status_code,
             "headers": keep, "text": resp.text,
             "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    path.write_text(json.dumps(entry))
    return entry


def get_json(url: str, params: dict | None = None):
    entry = get(url, params)
    if entry["status"] != 200:
        return None
    return json.loads(entry["text"])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, retries: int = 5) -> dict:
    """Download to dest (skipped if already present). Returns {path, sha256, bytes}."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        resp = _request(url, None, stream=True, retries=retries)
        resp.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return {"path": str(dest), "sha256": sha256_file(dest), "bytes": dest.stat().st_size}
