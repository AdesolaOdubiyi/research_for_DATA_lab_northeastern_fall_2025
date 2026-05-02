"""HTML + JSON parsing for title search and paginated episode-list payloads (no HTTP)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_show_search_results(html: str, show_name: str) -> Optional[str]:
    """Extract first title id from a search-results HTML document."""
    logger.info("Catalog search input show_name=%s", show_name[:120])
    soup = BeautifulSoup(html, "html.parser")
    results = soup.find_all("li", class_="find-result-item")
    if not results:
        results = soup.find_all("td", class_="result_text")
    for result in results:
        link = result.find("a", href=re.compile(r"/title/tt\d+/"))
        if not link:
            continue
        href = link.get("href", "")
        catalog_id_match = re.search(r"/title/(tt\d+)/", href)
        if not catalog_id_match:
            continue
        title_id = catalog_id_match.group(1)
        result_text = result.get_text()
        if re.search(r"\(\d{4}[-–]\s*\)", result_text) or "TV Series" in result_text:
            logger.debug("Found TV-style listing title_id=%s", title_id)
            return title_id
        logger.debug("Found candidate listing title_id=%s", title_id)
        return title_id
    logger.warning("No search results for show_name=%s", show_name[:120])
    return None


def detect_captcha(html: str) -> bool:
    """Return True if HTML looks like an anti-automation challenge page."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    if title and "robot" in title.get_text().lower():
        return True
    if soup.find("form", id="captchaForm"):
        return True
    if soup.find("div", class_="g-recaptcha"):
        return True
    return False


def parse_graphql_episodes(response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize one page of episode-list JSON into internal episode dicts."""
    episodes: List[Dict[str, Any]] = []
    try:
        title_data = response_data.get("data", {}).get("title", {})
        if not title_data:
            return []
        episodes_container = title_data.get("episodes", {})
        if not episodes_container:
            return []
        episodes_node = episodes_container.get("episodes", {})
        if not episodes_node:
            return []
        edges = episodes_node.get("edges", [])
        for edge in edges:
            node = edge.get("node", {})
            if not node:
                continue
            title_text = (node.get("titleText") or {}).get("text", "")
            raw_id = node.get("id") or ""
            id_match = re.search(r"(tt\d+)", str(raw_id))
            episode_id = id_match.group(1) if id_match else str(raw_id)
            release_date: Optional[Dict[str, int]] = None
            release_raw = node.get("releaseDate") or {}
            if isinstance(release_raw, dict) and release_raw.get("year") is not None:
                release_date = {
                    "year": int(release_raw["year"]),
                    "month": int(release_raw.get("month") or 1),
                    "day": int(release_raw.get("day") or 1),
                }
            episodes.append(
                {
                    "catalog_episode_id": episode_id,
                    "title": title_text,
                    "rating": (node.get("ratingsSummary") or {}).get("aggregateRating"),
                    "vote_count": (node.get("ratingsSummary") or {}).get("voteCount", 0),
                    "release_date": release_date,
                }
            )
    except (TypeError, KeyError, ValueError, AttributeError) as parse_error:
        logger.error("GraphQL episode parse failed error=%s", parse_error)
        return []
    return episodes
