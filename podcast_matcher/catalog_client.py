"""HTTP client for a third-party **title catalog** (search HTML + paginated JSON API).

1. **Offline mode (default)** — Reads the bundled sample file (see ``config.yaml`` /
   ``OFFLINE_CATALOG_SAMPLE_PATH``) so the pipeline runs with **no network** and no
   vendor URLs in git.
2. **Live HTTP** — When ``CATALOG_HTTP_ENABLED=1`` and all ``CATALOG_*`` variables are set,
   performs real requests: HTML search, title page GET, and persisted-query GraphQL
   pagination. **URLs, origins, referrers, and query hashes** come **only** from the
   environment (typically a private ``.env``), never from string literals here.

In **offline mode**, search results, title HTML, and episode rows come from committed
JSON/HTML so behavior is reproducible without calling a live site.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

import podcast_matcher.config as config
from podcast_matcher import html_catalog

logger = logging.getLogger(__name__)

GRAPHQL_EPISODES_PAGE_SIZE = 50
GRAPHQL_EPISODES_MAX_PAGES = 100
LIVE_REQUIRED_ENV_NAMES: Sequence[str] = (
    "CATALOG_SEARCH_URL_PODCAST_TEMPLATE",
    "CATALOG_TITLE_PAGE_URL_TEMPLATE",
    "CATALOG_GRAPHQL_HTTP_URL",
    "CATALOG_HTTP_ORIGIN_HEADER",
    "CATALOG_HTTP_REFERER_HEADER",
    "CATALOG_GRAPHQL_PERSISTED_HASH",
    "CATALOG_GRAPHQL_VARIABLES_RETURN_URL",
)


def _graphql_episode_page_from_response(
    response_json: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], bool, Optional[str]]:
    """Episode rows on this GraphQL page, whether more pages exist, and cursor for the next page."""
    page_episodes = html_catalog.parse_graphql_episodes(response_json)
    episodes_branch = (
        response_json.get("data", {})
        .get("title", {})
        .get("episodes", {})
        .get("episodes", {})
    )
    if not isinstance(episodes_branch, dict):
        return page_episodes, False, None
    page_info = episodes_branch.get("pageInfo", {})
    if not isinstance(page_info, dict):
        return page_episodes, False, None
    has_next_page = bool(page_info.get("hasNextPage"))
    end_cursor = page_info.get("endCursor")
    next_cursor = str(end_cursor) if has_next_page and end_cursor else None
    return page_episodes, has_next_page, next_cursor


class CaptchaDetectedError(Exception):
    """Raised when a search response looks like an anti-automation challenge."""


class AbortSignalError(Exception):
    """Raised when ``abort.txt`` is present in the repo root."""


@dataclass(frozen=True)
class LiveCatalogSettings:
    """Live integration strings from the process environment only."""

    search_podcast_template: str
    search_fallback_template: Optional[str]
    title_page_template: str
    graphql_http_url: str
    http_origin_header: str
    http_referer_header: str
    graphql_operation_name: str
    graphql_persisted_hash: str
    graphql_variables_return_url: str


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _require_env(name: str) -> str:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        raise ValueError(f"Missing required environment variable: {name}")
    return raw_value


def _validate_template_contains(template_value: str, required_placeholder: str, env_name: str) -> None:
    if required_placeholder not in template_value:
        raise ValueError(f"{env_name} must contain the literal substring {required_placeholder}")


def _missing_required_env(required_names: Sequence[str]) -> List[str]:
    return [env_name for env_name in required_names if not os.environ.get(env_name, "").strip()]


def _load_live_settings() -> Optional[LiveCatalogSettings]:
    """
    Build live settings from ``CATALOG_*`` env vars.

    Returns ``None`` when live mode is disabled (caller stays in offline mode).
    Raises ``ValueError`` when live mode is enabled but any required variable is missing or invalid.
    """
    if not _truthy_env("CATALOG_HTTP_ENABLED"):
        return None
    missing = _missing_required_env(LIVE_REQUIRED_ENV_NAMES)
    if missing:
        raise ValueError(
            "CATALOG_HTTP_ENABLED is set but the following variables are empty: "
            + ", ".join(missing)
        )
    podcast_tpl = _require_env("CATALOG_SEARCH_URL_PODCAST_TEMPLATE")
    _validate_template_contains(podcast_tpl, "{query}", "CATALOG_SEARCH_URL_PODCAST_TEMPLATE")
    title_tpl = _require_env("CATALOG_TITLE_PAGE_URL_TEMPLATE")
    _validate_template_contains(
        title_tpl,
        "{catalog_show_id}",
        "CATALOG_TITLE_PAGE_URL_TEMPLATE",
    )
    fallback = os.environ.get("CATALOG_SEARCH_URL_FALLBACK_TEMPLATE", "").strip() or None
    if fallback is not None and "{query}" not in fallback:
        raise ValueError("CATALOG_SEARCH_URL_FALLBACK_TEMPLATE must contain {query} when set")
    operation_name = (
        os.environ.get("CATALOG_GRAPHQL_OPERATION_NAME", "").strip() or "TitleEpisodesSubPagePagination"
    )
    return LiveCatalogSettings(
        search_podcast_template=podcast_tpl,
        search_fallback_template=fallback,
        title_page_template=title_tpl,
        graphql_http_url=_require_env("CATALOG_GRAPHQL_HTTP_URL"),
        http_origin_header=_require_env("CATALOG_HTTP_ORIGIN_HEADER"),
        http_referer_header=_require_env("CATALOG_HTTP_REFERER_HEADER"),
        graphql_operation_name=operation_name,
        graphql_persisted_hash=_require_env("CATALOG_GRAPHQL_PERSISTED_HASH"),
        graphql_variables_return_url=_require_env("CATALOG_GRAPHQL_VARIABLES_RETURN_URL"),
    )


class TitleCatalogClient:
    """
    Third-party title catalog: **offline mode by default**, **live HTTP** when ``CATALOG_*``
    is configured in the environment.
    """
    def __init__(self, offline_vendor_json_path: Optional[Path] = None) -> None:
        path = offline_vendor_json_path or config.OFFLINE_CATALOG_SAMPLE_PATH
        self._offline_vendor_json_path = path
        self._data = self._load_offline_vendor_data(path)
        self._live: Optional[LiveCatalogSettings] = None
        self._session: Optional[requests.Session] = None
        self.last_request_time = 0.0
        self.consecutive_503s = 0
        self.consecutive_network_errors = 0
        self.total_requests = 0
        self._initialize_live_http()

    def search_show(self, show_name: str) -> Optional[str]:
        """Resolve a catalog title id for ``show_name`` (live HTML search or offline mode)."""
        if self._live is None:
            return self._search_offline_vendor_json(show_name)
        return self._search_show_live(show_name)

    def fetch_title_page(self, catalog_show_id: str) -> Optional[str]:
        """Fetch HTML for a title detail page (GET from env template, or offline mode)."""
        if self._live is None:
            return self._fetch_title_page_offline(catalog_show_id)
        live = self._live
        url = live.title_page_template.format(catalog_show_id=catalog_show_id)
        response = self._request_with_retry(url, context=f"title_page:{catalog_show_id}")
        return response.text if response else None

    def fetch_episodes(self, catalog_show_id: str) -> List[Dict[str, Any]]:
        """Return all episodes for a show (GraphQL pagination when live; else offline mode)."""
        if self._live is None:
            return self._fetch_offline_episodes(catalog_show_id)
        all_episodes = self._paginate_live_episodes(catalog_show_id)
        self._reset_circuit_breaker_counters()
        logger.info("Fetched %s catalog episodes for %s", len(all_episodes), catalog_show_id)
        return all_episodes

    def _load_offline_vendor_data(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        logger.warning("Offline catalog sample file missing path=%s", path)
        return {}

    def _initialize_live_http(self) -> None:
        try:
            live = _load_live_settings()
        except ValueError as config_error:
            logger.error("Live catalog misconfigured: %s", config_error)
            raise
        if live is None:
            return
        self._live = live
        self._session = requests.Session()
        self._session.headers.update(self._live_session_headers())
        logger.warning(
            "Live catalog HTTP enabled, please ensure you comply with vendor terms and data agreements."
        )

    def _live_session_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _search_show_live(self, show_name: str) -> Optional[str]:
        assert self._live is not None
        encoded_show_name = requests.utils.quote(show_name)
        primary_url = self._live.search_podcast_template.format(query=encoded_show_name)
        resolved_catalog_show_id = self._search_show_live_url(primary_url, show_name, is_fallback=False)
        if resolved_catalog_show_id:
            return resolved_catalog_show_id
        fallback_template = self._live.search_fallback_template
        if not fallback_template:
            return None
        fallback_url = fallback_template.format(query=encoded_show_name)
        return self._search_show_live_url(fallback_url, show_name, is_fallback=True)

    def _search_show_live_url(
        self,
        search_url: str,
        show_name: str,
        *,
        is_fallback: bool,
    ) -> Optional[str]:
        context_prefix = "search_fallback" if is_fallback else "search"
        response = self._request_with_retry(search_url, context=f"{context_prefix}:{show_name[:60]}")
        if not response:
            return None
        if html_catalog.detect_captcha(response.text):
            raise CaptchaDetectedError("Search page looks like a challenge response")
        return html_catalog.parse_show_search_results(response.text, show_name)

    def _search_offline_vendor_json(self, show_name: str) -> Optional[str]:
        mapping = self._data.get("search_by_show_name", {})
        entry = mapping.get(show_name.strip())
        if not entry:
            logger.info("Offline mode: no catalog match for show_name=%s", show_name[:80])
            return None
        matched_catalog_show_id = entry.get("hit_catalog_show_id") or entry.get("hit_tconst")
        return str(matched_catalog_show_id) if matched_catalog_show_id else None

    def _fetch_title_page_offline(self, catalog_show_id: str) -> Optional[str]:
        pages = self._data.get("title_pages_by_tconst", {}) or self._data.get(
            "title_pages_by_show_id", {}
        )
        page_html = pages.get(catalog_show_id)
        return str(page_html) if page_html else None

    def _fetch_offline_episodes(self, catalog_show_id: str) -> List[Dict[str, Any]]:
        by_show = self._data.get("episodes_by_show_tconst", {}) or self._data.get(
            "episodes_by_show_id", {}
        )
        episode_rows = by_show.get(catalog_show_id, [])
        return list(episode_rows)

    def _paginate_live_episodes(self, catalog_show_id: str) -> List[Dict[str, Any]]:
        all_episodes: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None
        for page_index in range(1, GRAPHQL_EPISODES_MAX_PAGES + 1):
            payload = self._build_graphql_episodes_payload(catalog_show_id, next_cursor)
            response_json = self._post_graphql_episodes_json(payload, page_index=page_index)
            if response_json is None:
                break
            page_episodes, has_next_page, next_cursor = _graphql_episode_page_from_response(
                response_json
            )
            if not page_episodes:
                break
            all_episodes.extend(page_episodes)
            if not has_next_page or not next_cursor:
                break
        else:
            logger.warning(
                "Stopped pagination at page %s show=%s",
                GRAPHQL_EPISODES_MAX_PAGES,
                catalog_show_id,
            )
        return all_episodes

    def _build_graphql_episodes_payload(
        self, catalog_show_id: str, after_cursor: Optional[str]
    ) -> Dict[str, Any]:
        assert self._live is not None
        live = self._live
        variables: Dict[str, Any] = {
            "const": catalog_show_id,
            "filter": {"includeSeasons": ["unknown"]},
            "first": GRAPHQL_EPISODES_PAGE_SIZE,
            "locale": "en-US",
            "originalTitleText": False,
            "returnUrl": live.graphql_variables_return_url,
            "sort": {"by": "EPISODE_THEN_RELEASE", "order": "ASC"},
            "after": after_cursor if after_cursor else "",
        }
        return {
            "operationName": live.graphql_operation_name,
            "variables": variables,
            "extensions": {
                "persistedQuery": {
                    "sha256Hash": live.graphql_persisted_hash,
                    "version": 1,
                }
            },
        }

    def _post_graphql_episodes_json(
        self, payload: Dict[str, Any], *, page_index: int
    ) -> Optional[Dict[str, Any]]:
        assert self._session is not None and self._live is not None
        live = self._live
        self._throttle()
        try:
            response = self._session.post(
                live.graphql_http_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Origin": live.http_origin_header,
                    "Referer": live.http_referer_header,
                },
                timeout=config.HTTP_REQUEST_TIMEOUT,
            )
            self.total_requests += 1
            if response.status_code != 200:
                logger.warning("GraphQL HTTP %s", response.status_code)
                return None
            response_json = response.json()
            if response_json.get("errors"):
                logger.warning("GraphQL errors=%s", response_json.get("errors"))
                return None
            return response_json
        except (requests.RequestException, ValueError) as graphql_error:
            logger.error("GraphQL page failed page=%s error=%s", page_index, graphql_error)
            return None

    def _request_with_retry(self, url: str, context: str) -> Optional[requests.Response]:
        if self._session is None:
            return None
        for attempt in range(config.HTTP_MAX_RETRIES):
            self._throttle()
            try:
                response = self._session.get(url, timeout=config.HTTP_REQUEST_TIMEOUT)
                self.total_requests += 1
            except requests.Timeout:
                logger.warning("Timeout attempt=%s context=%s", attempt + 1, context)
                time.sleep(2**attempt)
                continue
            except requests.RequestException as request_error:
                self.consecutive_network_errors += 1
                logger.warning(
                    "Network error context=%s consecutive=%s error=%s",
                    context,
                    self.consecutive_network_errors,
                    request_error,
                )
                if self.consecutive_network_errors >= config.CB_MAX_CONSECUTIVE_NETWORK_ERRORS:
                    self._pause_for_circuit_breaker("too many consecutive network errors")
                time.sleep(2**attempt)
                continue
            handled_response, should_stop_retrying = self._evaluate_get_response_outcome(
                response,
                context=context,
                attempt=attempt,
            )
            if handled_response is not None:
                return handled_response
            if should_stop_retrying:
                return None
        logger.error("Exhausted retries context=%s", context)
        return None

    def _evaluate_get_response_outcome(
        self,
        response: requests.Response,
        *,
        context: str,
        attempt: int,
    ) -> Tuple[Optional[requests.Response], bool]:
        if response.status_code == 200:
            self._reset_circuit_breaker_counters()
            return response, True
        if response.status_code == 503:
            self.consecutive_503s += 1
            logger.warning(
                "503 from catalog context=%s consecutive=%s",
                context,
                self.consecutive_503s,
            )
            if self.consecutive_503s >= config.CB_MAX_CONSECUTIVE_503S:
                self._pause_for_circuit_breaker("too many consecutive 503 responses")
            if self.consecutive_503s == config.CB_EARLY_WARNING_503S:
                logger.warning("Early warning: elevated 503 rate context=%s", context)
            time.sleep((attempt + 1) * 30)
            return None, False
        if response.status_code == 429:
            time.sleep(60 * (2**attempt))
            return None, False
        if response.status_code == 404:
            return None, True
        logger.warning("HTTP %s context=%s", response.status_code, context)
        return None, True

    def _reset_circuit_breaker_counters(self) -> None:
        self.consecutive_503s = 0
        self.consecutive_network_errors = 0

    def _pause_for_circuit_breaker(self, reason: str) -> None:
        logger.critical("Circuit breaker: %s — pausing %ss", reason, config.CB_PAUSE_SECONDS)
        time.sleep(config.CB_PAUSE_SECONDS)
        if self._consume_abort_signal():
            raise AbortSignalError(reason)
        self._reset_circuit_breaker_counters()

    def _throttle(self) -> None:
        now = time.time()
        delta = now - self.last_request_time
        if delta < config.HTTP_BASE_DELAY:
            time.sleep(config.HTTP_BASE_DELAY - delta)
        self.last_request_time = time.time()

    def _consume_abort_signal(self) -> bool:
        abort_file = config.ROOT_DIR / "abort.txt"
        if not abort_file.is_file():
            return False
        logger.critical("abort.txt present, removing and stopping")
        try:
            abort_file.unlink()
        except OSError as unlink_error:
            logger.warning("Failed to remove abort signal file path=%s error=%s", abort_file, unlink_error)
        return True
