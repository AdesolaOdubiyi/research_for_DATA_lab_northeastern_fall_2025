"""Title-index client: offline fixtures for this public export.

Live HTTP against third-party services is intentionally not implemented here.
Integration endpoints and payloads belong in private configuration or research
archives, not in a public repository.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import podcast_matcher.config as config

logger = logging.getLogger(__name__)


class IMDbClient:
    """Resolve show pages and episode lists using committed JSON fixtures."""

    def __init__(self, fixture_path: Optional[Path] = None) -> None:
        path = fixture_path or config.OFFLINE_VENDOR_FIXTURE_PATH
        self._fixture_path = path
        self._data: Dict[str, Any] = {}
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))
        else:
            logger.warning("Offline fixture missing path=%s", path)

    def search_show(self, show_name: str) -> Optional[str]:
        """Return a synthetic title id for ``show_name`` when present in fixtures."""
        mapping = self._data.get("search_by_show_name", {})
        entry = mapping.get(show_name.strip())
        if not entry:
            logger.info("Offline fixture: no search hit for show_name=%s", show_name[:80])
            return None
        tconst = entry.get("hit_tconst")
        logger.debug("Offline search hit show_name=%s tconst=%s", show_name[:80], tconst)
        return str(tconst) if tconst else None

    def fetch_title_page(self, tconst: str) -> Optional[str]:
        """Return minimal HTML used by show validation heuristics."""
        pages = self._data.get("title_pages_by_tconst", {})
        html = pages.get(tconst)
        if html:
            return str(html)
        logger.warning("Offline fixture: no title page for tconst=%s", tconst)
        return None

    def fetch_episodes(self, tconst: str) -> List[Dict[str, Any]]:
        """Return episode dicts (title, ids, optional rating, release_date)."""
        eps = self._data.get("episodes_by_show_tconst", {}).get(tconst, [])
        if not eps:
            logger.warning("Offline fixture: no episodes for tconst=%s", tconst)
        return list(eps)
