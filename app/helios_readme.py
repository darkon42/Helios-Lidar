"""Server-side fetch + render of the Helios card README.

The `/helios-card` page on helios-lidar.org wants to show the README
of the currently-published Helios release, but doing the fetch from
the browser would (a) burn through anonymous GitHub API rate limits
faster than necessary and (b) leak GitHub UA strings from every
visitor. So we fetch + render server-side, cache the rendered HTML
for an hour, and expose it through a single JSON endpoint that the
static helios-card.html page consumes via fetch().

The fetch path:

  1. GET https://api.github.com/repos/ReikanYsora/Helios/releases/latest
     to learn the latest release tag,
  2. GET https://raw.githubusercontent.com/ReikanYsora/Helios/{tag}/README.md
     to grab the markdown as it shipped with that release,
  3. render the markdown to HTML via `markdown` with the extensions
     the README actually uses (fenced code, tables, sane lists, toc).

If GitHub is down or rate-limits us, we serve the last successfully
cached HTML so the page degrades gracefully. If we have nothing
cached either, we surface a small placeholder asking the user to
retry, with a direct link to the GitHub repo as the manual fallback.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import NamedTuple

import markdown

log = logging.getLogger("helios-lidar")

#GitHub repo coordinates. Hard-coded because this page exclusively
#mirrors the official Helios card README; configurability would just
#dilute the contract.
GITHUB_OWNER = "ReikanYsora"
GITHUB_REPO = "Helios"

#One hour TTL. Releases happen at most every few weeks; an hour of
#staleness is invisible to users and keeps us well under GitHub's
#60 req/h anonymous quota.
CACHE_TTL_SECONDS = 60 * 60

#Hard cap on the README size so a hostile redirect or malformed
#response can't pin the worker. The real README is ~20 KB.
MAX_README_BYTES = 512 * 1024

#How long we let an HTTP call hang before giving up.
HTTP_TIMEOUT_SECONDS = 10


class HeliosReadmeRender(NamedTuple):
    html: str
    release_tag: str
    release_url: str
    fetched_at_unix: float


_cache: HeliosReadmeRender | None = None
_lock = threading.Lock()


def _http_get_text(url: str) -> str:
    """GET a URL with a polite UA, surface the body as text, fail loud
    on any non-2xx so the caller can fall back to the stale cache."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "helios-lidar/1.0 (+https://helios-lidar.org)",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        raw = resp.read(MAX_README_BYTES + 1)
    if len(raw) > MAX_README_BYTES:
        raise ValueError(f"Response from {url} exceeds {MAX_README_BYTES} bytes")
    return raw.decode("utf-8", errors="replace")


def _render_markdown(md_text: str) -> str:
    """Render the README markdown to HTML, with the extensions the
    Helios README actually depends on. Output is trusted because the
    source is our own repo, so we don't run a sanitiser pass.
    """
    return markdown.markdown(
        md_text,
        extensions=[
            "fenced_code",
            "tables",
            "sane_lists",
            "toc",
        ],
        output_format="html5",
    )


def _fetch_fresh() -> HeliosReadmeRender:
    """One-shot fetch + render. Raises on any failure so the caller
    can fall back to the cached value (if any).
    """
    release_json = _http_get_text(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    )
    release = json.loads(release_json)
    tag = release.get("tag_name") or "main"
    release_url = release.get("html_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

    md_text = _http_get_text(
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{tag}/README.md"
    )
    html = _render_markdown(md_text)
    return HeliosReadmeRender(
        html=html,
        release_tag=tag,
        release_url=release_url,
        fetched_at_unix=time.time(),
    )


def get_rendered_readme() -> HeliosReadmeRender | None:
    """Return the cached render if fresh, otherwise refresh in-place.

    Returns the stale cache on fetch errors. Returns None only if we
    have never successfully fetched the README in this process.
    """
    global _cache
    with _lock:
        now = time.time()
        if _cache is not None and (now - _cache.fetched_at_unix) < CACHE_TTL_SECONDS:
            return _cache
        try:
            _cache = _fetch_fresh()
            return _cache
        except (urllib.error.URLError, ValueError, json.JSONDecodeError, TimeoutError):
            log.exception("Helios README fetch failed; serving stale cache if any")
            return _cache
