"""Show validation and episode-level fuzzy matching."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from rapidfuzz import fuzz

import podcast_matcher.config as config
from podcast_matcher.catalog_client import TitleCatalogClient
from podcast_matcher.utils import dates_match, normalize_title

logger = logging.getLogger(__name__)


def _strip_catalog_page_suffix(og_title: str) -> str:
    """Drop trailing `` - SiteName`` style suffixes common on third-party title pages."""
    if " - " not in og_title:
        return og_title.strip()
    return og_title.rsplit(" - ", 1)[0].strip()


def score_podcast_likelihood(soup: BeautifulSoup, page_text: str) -> Tuple[bool, int, str]:
    """Heuristic to determine if a title behaves like a podcast."""
    score = 0
    reasons: List[str] = []
    lower_text = page_text.lower()
    explicit = config.SHOW_VALIDATION_EXPLICIT_PODCAST_PAGE_SCORE
    pass_min = config.SHOW_VALIDATION_PODCAST_LIKE_PASS_MINIMUM

    if "podcast series" in lower_text or "podcast episode" in lower_text:
        return True, explicit, "Explicit podcast"

    description = ""
    plot_elem = soup.find("span", attrs={"data-testid": "plot-xl"})
    if plot_elem:
        description = plot_elem.get_text(strip=True).lower()
    else:
        meta_desc = soup.find("meta", property="og:description")
        if meta_desc:
            description = meta_desc.get("content", "").lower()

    if description:
        if "podcast" in description:
            score += config.SHOW_VALIDATION_SCORE_DESCRIPTION_PODCAST
            reasons.append("podcast in description")
        if "episode" in description:
            score += config.SHOW_VALIDATION_SCORE_DESCRIPTION_EPISODE
            reasons.append("episode in description")
        if "hosted by" in description or "presented by" in description:
            score += config.SHOW_VALIDATION_SCORE_DESCRIPTION_HOSTED
            reasons.append("hosted/presented indicator")
        if "weekly" in description or "daily" in description:
            score += config.SHOW_VALIDATION_SCORE_DESCRIPTION_WEEKLY_DAILY
            reasons.append("weekly/daily cadence")
        if "guests" in description or "special guests" in description:
            score += config.SHOW_VALIDATION_SCORE_DESCRIPTION_GUESTS
            reasons.append("'guests' in description")

    cast_section = soup.find("section", attrs={"data-testid": "title-cast"})
    if cast_section:
        cast_items = cast_section.find_all("a", href=re.compile(r"/name/"))
        if len(cast_items) > config.SHOW_VALIDATION_LARGE_CAST_MINIMUM_LINKS:
            score -= config.SHOW_VALIDATION_LARGE_CAST_PENALTY
            reasons.append("large cast")

    genre_links = soup.find_all("a", href=re.compile(r"/search/title\?genres="))
    for link in genre_links:
        genre = link.get_text(strip=True).lower()
        if genre in {"talk-show", "news", "comedy"}:
            score += config.SHOW_VALIDATION_GENRE_KEYWORD_BOOST
            reasons.append(f"genre {genre}")

    return score >= pass_min, score, "; ".join(reasons) if reasons else "No indicators"


def extract_parent_show_id(soup: BeautifulSoup, current_show_id: str) -> Optional[str]:
    """Return parent series catalog id when the current page is an episode listing."""
    link = soup.find("a", href=re.compile(r"/title/tt\d+/episodes"))
    if link:
        href_match = re.search(r"/title/(tt\d+)/", link.get("href", ""))
        if href_match and href_match.group(1) != current_show_id:
            return href_match.group(1)

    breadcrumbs = soup.find_all("a", href=re.compile(r"/title/tt\d+/"))
    for crumb in breadcrumbs:
        href = crumb.get("href", "")
        crumb_match = re.search(r"/title/(tt\d+)/", href)
        if crumb_match:
            parent_id = crumb_match.group(1)
            if parent_id != current_show_id and "/episodes" not in href:
                text = crumb.get_text(strip=True).lower()
                if "episode" not in text or "all episodes" in text:
                    return parent_id

    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            linked_payload = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(linked_payload, dict):
            for series_key in ("partOfSeries", "parentItem"):
                if series_key in linked_payload and isinstance(linked_payload[series_key], dict):
                    id_match = re.search(
                        r"/title/(tt\d+)", linked_payload[series_key].get("@id", "")
                    )
                    if id_match:
                        return id_match.group(1)
    meta_parent = soup.find(
        "meta",
        property=lambda property_value: isinstance(property_value, str)
        and property_value.endswith(":parentSeries"),
    )
    if meta_parent:
        content_match = re.search(r"tt\d+", meta_parent.get("content", ""))
        if content_match:
            return content_match.group(0)
    return None


def _read_catalog_title_page(
    catalog_client: TitleCatalogClient,
    catalog_show_id: str,
) -> Tuple[Optional[BeautifulSoup], Optional[str], str]:
    """Load HTML, parse soup, and resolve visible catalog title text."""
    page_html = catalog_client.fetch_title_page(catalog_show_id)
    if not page_html:
        return None, None, ""
    soup = BeautifulSoup(page_html, "html.parser")
    page_text_lower = page_html.lower()
    title_elem = soup.find("h1", attrs={"data-testid": "hero-title-block__title"})
    catalog_title = title_elem.get_text(strip=True) if title_elem else None
    if not catalog_title:
        meta_title = soup.find("meta", property="og:title")
        if meta_title:
            catalog_title = _strip_catalog_page_suffix(meta_title.get("content", ""))
    return soup, catalog_title, page_text_lower


def _series_year_exceeds_reject_threshold(catalog_title: str) -> bool:
    year_match = re.search(r"\((?:Podcast|TV) Series (\d{4})", catalog_title)
    if not year_match:
        return False
    return int(year_match.group(1)) > config.SHOW_VALIDATION_REJECT_SERIES_YEAR_AFTER


def _keyword_coverage_and_similarity(
    original_show_name: str, catalog_title: str
) -> Tuple[float, float, set[str]]:
    original_norm = normalize_title(original_show_name)
    catalog_norm = normalize_title(catalog_title)
    original_words = set(original_norm.split())
    catalog_words = set(catalog_norm.split())
    common_words = {"podcast", "the", "a", "an", "and", "of", "with", "by", "series"}

    def filter_words(words: set[str]) -> set[str]:
        return {word for word in words if word and word not in common_words and not word.isdigit()}

    original_keywords = filter_words(original_words)
    catalog_keywords = filter_words(catalog_words)
    matching_keywords = original_keywords & catalog_keywords
    coverage = len(matching_keywords) / len(original_keywords) if original_keywords else 0
    similarity = float(fuzz.token_set_ratio(original_norm, catalog_norm))
    return similarity, coverage, original_keywords


def _similarity_rules_reject(
    original_keywords: set[str],
    coverage: float,
    similarity: float,
    similarity_threshold_percent: int,
) -> bool:
    cov_min = config.SHOW_VALIDATION_KEYWORD_COVERAGE_MINIMUM
    cov_fallback_sim = config.SHOW_VALIDATION_COVERAGE_FALLBACK_SIMILARITY_PERCENT
    if not original_keywords and similarity < similarity_threshold_percent:
        return True
    if original_keywords and coverage < cov_min and similarity < cov_fallback_sim:
        return True
    return False


def _podcast_heuristic_verdict(
    soup: BeautifulSoup, page_text_lower: str
) -> Tuple[bool, Optional[str], int, str]:
    """
    Returns ``(reject, risk_label, podcast_score, reason)``.
    ``reject`` is True when the score is below the hard cutoff.
    """
    _, podcast_score, reason = score_podcast_likelihood(soup, page_text_lower)
    reject_below = config.SHOW_VALIDATION_REJECT_BELOW_PODCAST_SCORE
    if podcast_score < reject_below:
        return True, None, podcast_score, reason
    high_below = config.SHOW_VALIDATION_RISK_HIGH_BELOW_SCORE
    medium_below = config.SHOW_VALIDATION_RISK_MEDIUM_BELOW_SCORE
    if podcast_score < high_below:
        return False, "high", podcast_score, reason
    if podcast_score < medium_below:
        return False, "medium", podcast_score, reason
    return False, "low", podcast_score, reason


def _validate_show_match_core(
    catalog_client: TitleCatalogClient,
    catalog_show_id: str,
    original_show_name: str,
    recursion_depth: int,
    similarity_threshold_percent: int,
) -> Tuple[bool, Optional[str], Optional[float], Optional[str], Optional[str]]:
    """Shared validation body for show vs catalog title pages."""
    if recursion_depth > config.SHOW_VALIDATION_MAX_RECURSION_DEPTH:
        return False, None, None, None, None

    soup, catalog_title, page_text_lower = _read_catalog_title_page(
        catalog_client, catalog_show_id
    )
    if soup is None or not catalog_title:
        return False, None, None, None, None

    if "podcast episode" in catalog_title.lower():
        parent_show_id = extract_parent_show_id(soup, catalog_show_id)
        if parent_show_id:
            return validate_show_match_as_parent_series(
                catalog_client,
                parent_show_id,
                original_show_name,
                recursion_depth + 1,
            )

    if _series_year_exceeds_reject_threshold(catalog_title):
        return False, catalog_title, None, None, None

    similarity, coverage, original_keywords = _keyword_coverage_and_similarity(
        original_show_name, catalog_title
    )
    if _similarity_rules_reject(
        original_keywords, coverage, similarity, similarity_threshold_percent
    ):
        return False, catalog_title, similarity, None, None

    reject, false_positive_risk, _, reason = _podcast_heuristic_verdict(soup, page_text_lower)
    if reject:
        return False, catalog_title, similarity, None, None

    logger.debug(
        "Validated show %s → %s (similarity=%s, coverage=%.2f, risk=%s, reason=%s)",
        original_show_name,
        catalog_title,
        similarity,
        coverage,
        false_positive_risk,
        reason,
    )
    return True, catalog_title, similarity, false_positive_risk, catalog_show_id


def validate_show_match(
    catalog_client: TitleCatalogClient,
    catalog_show_id: str,
    original_show_name: str,
    recursion_depth: int = 0,
) -> Tuple[bool, Optional[str], Optional[float], Optional[str], Optional[str]]:
    """Validate that ``catalog_show_id`` matches the original show name."""
    return _validate_show_match_core(
        catalog_client,
        catalog_show_id,
        original_show_name,
        recursion_depth,
        config.SHOW_SIMILARITY_THRESHOLD,
    )


def validate_show_match_as_parent_series(
    catalog_client: TitleCatalogClient,
    catalog_show_id: str,
    original_show_name: str,
    recursion_depth: int,
) -> Tuple[bool, Optional[str], Optional[float], Optional[str], Optional[str]]:
    """Validate after resolving an episode page to its parent series."""
    return _validate_show_match_core(
        catalog_client,
        catalog_show_id,
        original_show_name,
        recursion_depth,
        config.PARENT_SIMILARITY_THRESHOLD,
    )


def _best_catalog_row_for_episode(
    sporc_norm: str, catalog_episodes: List[Dict[str, object]]
) -> Tuple[Optional[Dict[str, object]], int]:
    best_row: Optional[Dict[str, object]] = None
    best_score = 0
    for catalog_episode_row in catalog_episodes:
        cat_norm = normalize_title(str(catalog_episode_row.get("title") or ""))
        if not cat_norm:
            continue
        score = fuzz.token_set_ratio(sporc_norm, cat_norm)
        if score == 100:
            return catalog_episode_row, score
        if score > best_score:
            best_score = score
            best_row = catalog_episode_row
    return best_row, best_score


def _match_row_from_best_catalog(
    sporc_ep: Dict[str, object],
    best_row: Optional[Dict[str, object]],
    best_score: int,
) -> Dict[str, object]:
    match_type = "unmatched"
    catalog_episode_id: Optional[str] = None
    catalog_rating: Optional[float] = None
    confidence = 0.0
    date_raw = sporc_ep.get("date")
    date_for_match: Optional[int] = None
    if isinstance(date_raw, (int, float)):
        date_for_match = int(date_raw)
    elif isinstance(date_raw, str) and date_raw.isdigit():
        date_for_match = int(date_raw)
    if best_row and best_score >= config.EPISODE_FUZZY_MEDIUM:
        release = best_row.get("release_date")
        release_dict = release if isinstance(release, dict) else None
        date_matches = dates_match(
            date_for_match,
            release_dict,
            config.DATE_TOLERANCE_DAYS,
        )
        if best_score >= config.EPISODE_FUZZY_HIGH or date_matches:
            raw_id = best_row.get("catalog_episode_id")
            catalog_episode_id = str(raw_id) if raw_id else None
            rating = best_row.get("rating")
            catalog_rating = float(rating) if rating is not None else None
            confidence = best_score / 100.0
            match_type = (
                "exact"
                if best_score == 100
                else ("fuzzy_high" if best_score >= config.EPISODE_FUZZY_HIGH else "fuzzy_medium")
            )
    return {
        "sporc_episode_name": sporc_ep["episode_name"],
        "sporc_episode_url": sporc_ep.get("episode_url"),
        "sporc_episode_date": date_raw,
        "sporc_duration": sporc_ep.get("duration_seconds"),
        "catalog_episode_id": catalog_episode_id,
        "catalog_rating": catalog_rating,
        "match_type": match_type,
        "confidence": confidence,
    }


def match_episodes(
    sporc_episodes: List[Dict[str, object]], catalog_episodes: List[Dict[str, object]]
) -> List[Dict[str, object]]:
    """Match source episodes to catalog episodes (fuzzy title + optional date guard)."""
    matched: List[Dict[str, object]] = []
    for sporc_ep in sporc_episodes:
        sporc_norm = normalize_title(str(sporc_ep["episode_name"]))
        best_row, best_score = _best_catalog_row_for_episode(sporc_norm, catalog_episodes)
        matched.append(_match_row_from_best_catalog(sporc_ep, best_row, best_score))
    return matched
