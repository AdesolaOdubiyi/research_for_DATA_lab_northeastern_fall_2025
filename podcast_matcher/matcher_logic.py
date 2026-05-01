"""Show validation and episode-level fuzzy matching."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from rapidfuzz import fuzz

import podcast_matcher.config as config
from podcast_matcher.imdb_client import IMDbClient
from podcast_matcher.utils import dates_match, normalize_title

logger = logging.getLogger(__name__)


def check_if_podcast_like(soup: BeautifulSoup, page_text: str) -> Tuple[bool, int, str]:
    """Heuristic to determine if a title behaves like a podcast."""
    score = 0
    reasons: List[str] = []
    lower_text = page_text.lower()

    if "podcast series" in lower_text or "podcast episode" in lower_text:
        return True, 10, "Explicit podcast"

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
            score += 3
            reasons.append("podcast in description")
        if "episode" in description:
            score += 2
            reasons.append("episode in description")
        if "hosted by" in description or "presented by" in description:
            score += 2
            reasons.append("hosted/presented indicator")
        if "weekly" in description or "daily" in description:
            score += 1
            reasons.append("weekly/daily cadence")
        if "guests" in description or "special guests" in description:
            score += 1
            reasons.append("'guests' in description")

    cast_section = soup.find("section", attrs={"data-testid": "title-cast"})
    if cast_section:
        cast_items = cast_section.find_all("a", href=re.compile(r"/name/nm\d+"))
        if len(cast_items) > 5:
            score -= 2
            reasons.append("large cast")

    genre_links = soup.find_all("a", href=re.compile(r"/search/title\?genres="))
    for link in genre_links:
        genre = link.get_text(strip=True).lower()
        if genre in {"talk-show", "news", "comedy"}:
            score += 1
            reasons.append(f"genre {genre}")

    return score >= 3, score, "; ".join(reasons) if reasons else "No indicators"


def extract_parent_series_tconst(soup: BeautifulSoup, current_tconst: str) -> Optional[str]:
    """Return parent series tconst for episode pages."""
    link = soup.find("a", href=re.compile(r"/title/tt\d+/episodes"))
    if link:
        match = re.search(r"/title/(tt\d+)/", link.get("href", ""))
        if match and match.group(1) != current_tconst:
            return match.group(1)

    breadcrumbs = soup.find_all("a", href=re.compile(r"/title/tt\d+/"))
    for crumb in breadcrumbs:
        href = crumb.get("href", "")
        match = re.search(r"/title/(tt\d+)/", href)
        if match:
            tconst = match.group(1)
            if tconst != current_tconst and "/episodes" not in href:
                text = crumb.get_text(strip=True).lower()
                if "episode" not in text or "all episodes" in text:
                    return tconst

    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for key in ("partOfSeries", "parentItem"):
                if key in data and isinstance(data[key], dict):
                    match = re.search(r"/title/(tt\d+)", data[key].get("@id", ""))
                    if match:
                        return match.group(1)
    meta_parent = soup.find("meta", property="imdb:parentSeries")
    if meta_parent:
        match = re.search(r"tt\d+", meta_parent.get("content", ""))
        if match:
            return match.group(0)
    return None


def validate_show_match(
    imdb_client: IMDbClient,
    tconst: str,
    original_show_name: str,
    recursion_depth: int = 0,
    is_parent_series: bool = False,
) -> Tuple[bool, Optional[str], Optional[float], Optional[str], Optional[str]]:
    """Validate that ``tconst`` matches the original show name."""
    if recursion_depth > 3:
        return False, None, None, None, None
    html = imdb_client.fetch_title_page(tconst)
    if not html:
        return False, None, None, None, None
    soup = BeautifulSoup(html, "html.parser")
    page_text = html.lower()
    title_elem = soup.find("h1", attrs={"data-testid": "hero-title-block__title"})
    imdb_title = title_elem.get_text(strip=True) if title_elem else None
    if not imdb_title:
        meta_title = soup.find("meta", property="og:title")
        if meta_title:
            imdb_title = meta_title.get("content", "").replace(" - IMDb", "").strip()
    if not imdb_title:
        return False, None, None, None, None

    if "podcast episode" in imdb_title.lower():
        parent = extract_parent_series_tconst(soup, tconst)
        if parent:
            return validate_show_match(
                imdb_client,
                parent,
                original_show_name,
                recursion_depth + 1,
                True,
            )

    year_match = re.search(r"\((?:Podcast|TV) Series (\d{4})", imdb_title)
    if year_match and int(year_match.group(1)) > 2020:
        return False, imdb_title, None, None, None

    original_norm = normalize_title(original_show_name)
    imdb_norm = normalize_title(imdb_title)
    original_words = set(original_norm.split())
    imdb_words = set(imdb_norm.split())
    common_words = {"podcast", "the", "a", "an", "and", "of", "with", "by", "series"}

    def filter_words(words: set[str]) -> set[str]:
        return {w for w in words if w and w not in common_words and not w.isdigit()}

    original_keywords = filter_words(original_words)
    imdb_keywords = filter_words(imdb_words)
    matching_keywords = original_keywords & imdb_keywords
    coverage = len(matching_keywords) / len(original_keywords) if original_keywords else 0
    similarity_threshold = (
        config.PARENT_SIMILARITY_THRESHOLD if is_parent_series else config.SHOW_SIMILARITY_THRESHOLD
    )
    similarity = float(fuzz.token_set_ratio(original_norm, imdb_norm))

    if not original_keywords and similarity < similarity_threshold:
        return False, imdb_title, similarity, None, None
    if original_keywords and coverage < 0.7 and similarity < 95:
        return False, imdb_title, similarity, None, None

    _is_podcast, podcast_score, reason = check_if_podcast_like(soup, page_text)
    false_positive_risk: Optional[str] = None
    if podcast_score < 0:
        return False, imdb_title, similarity, None, None
    if podcast_score < 3:
        false_positive_risk = "high"
    elif podcast_score < 10:
        false_positive_risk = "medium"
    else:
        false_positive_risk = "low"

    logger.debug(
        "Validated show %s → %s (similarity=%s, coverage=%.2f, risk=%s, reason=%s)",
        original_show_name,
        imdb_title,
        similarity,
        coverage,
        false_positive_risk,
        reason,
    )
    return True, imdb_title, similarity, false_positive_risk, tconst


def match_episodes(
    sporc_episodes: List[Dict[str, object]], imdb_episodes: List[Dict[str, object]]
) -> List[Dict[str, object]]:
    """Match source episodes to catalog episodes (fuzzy title + optional date guard)."""
    matched: List[Dict[str, object]] = []
    for sporc_ep in sporc_episodes:
        sporc_norm = normalize_title(str(sporc_ep["episode_name"]))
        best_match: Optional[Dict[str, object]] = None
        best_score = 0
        for imdb_ep in imdb_episodes:
            imdb_norm = normalize_title(str(imdb_ep.get("title") or ""))
            if not imdb_norm:
                continue
            score = fuzz.token_set_ratio(sporc_norm, imdb_norm)
            if score == 100:
                best_match = imdb_ep
                best_score = score
                break
            if score > best_score:
                best_score = score
                best_match = imdb_ep
        match_type = "unmatched"
        imdb_tconst: Optional[str] = None
        imdb_rating: Optional[float] = None
        confidence = 0.0
        date_raw = sporc_ep.get("date")
        date_for_match: Optional[int] = None
        if isinstance(date_raw, (int, float)):
            date_for_match = int(date_raw)
        elif isinstance(date_raw, str) and date_raw.isdigit():
            date_for_match = int(date_raw)
        if best_match and best_score >= config.EPISODE_FUZZY_MEDIUM:
            release = best_match.get("release_date")
            release_dict = release if isinstance(release, dict) else None
            date_matches = dates_match(
                date_for_match,
                release_dict,
                config.DATE_TOLERANCE_DAYS,
            )
            if best_score >= config.EPISODE_FUZZY_HIGH or date_matches:
                raw_t = best_match.get("tconst")
                imdb_tconst = str(raw_t) if raw_t else None
                rating = best_match.get("rating")
                imdb_rating = float(rating) if rating is not None else None
                confidence = best_score / 100.0
                match_type = (
                    "exact"
                    if best_score == 100
                    else ("fuzzy_high" if best_score >= config.EPISODE_FUZZY_HIGH else "fuzzy_medium")
                )
        matched.append(
            {
                "sporc_episode_name": sporc_ep["episode_name"],
                "sporc_episode_url": sporc_ep.get("episode_url"),
                "sporc_episode_date": date_raw,
                "sporc_duration": sporc_ep.get("duration_seconds"),
                "imdb_tconst": imdb_tconst,
                "imdb_rating": imdb_rating,
                "match_type": match_type,
                "confidence": confidence,
            }
        )
    return matched
