import re
import urllib.parse as ul
from typing import Any, Dict, List, Optional

from services.oba_config import (
    COLLECTION_BOOKS,
    COLLECTION_BOOKS_KN,
    COLLECTION_FAQ,
    COLLECTION_EVENTS,
)

FICTION_MAP = {
    "baby": ["prentenboeken baby"],
    "peuter": ["prentenboeken tot 4 jaar"],
    "kleuter": ["prentenboeken vanaf 4 jaar"],
    "kind": ["fictie tot 9 jaar", "fictie 9 tot 12 jaar"],
    "jeugd": ["fictie 9 tot 12 jaar", "fictie vanaf 12 jaar"],
    "oudere_jeugd": ["fictie vanaf 15 jaar"],
    "volwassen": ["fictie Volwassenen"],
}

NONFICTION_MAP = {
    "kind": ["info tot 9 jaar"],
    "jeugd": ["info vanaf 9 jaar"],
    "oudere_jeugd": ["info volwassenen"],
    "volwassen": ["info volwassenen"],
}

def _mk_filter_by(indeling_list: Optional[List[str]] = None, language: Optional[str] = None) -> str:
    parts = []
    if indeling_list:
        inner = "||".join([f"indeling:={opt}" for opt in indeling_list])
        parts.append(f"({inner})")
    if language:
        parts.append(f"language :={language}")
    return " && ".join(parts)

def _looks_author(text: str) -> bool:
    return bool(re.search(r"\b(auteur|schrijver|door|van)\b", text, re.I))

def _looks_title(text: str) -> bool:
    return bool(re.search(r"\btitel\b|\".+\"|\'[^\']+\'", text))

def _build_search_params(
    user_query: str,
    query_by_choice: Optional[str] = None,
    vector_alpha: Optional[float] = None,
    location_kraaiennest: Optional[bool] = False,
    audience: Optional[str] = None,
    content_type: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    text = (user_query or "").strip()
    filters = filters or {}
    language = filters.get("language")

    if query_by_choice:
        qb = query_by_choice
    else:
        if _looks_author(text) and not _looks_title(text):
            qb = "main_author"
        elif _looks_title(text) and not _looks_author(text):
            qb = "short_title"
        else:
            qb = "embedding"

    if qb.startswith("embedding"):
        alpha = vector_alpha if isinstance(vector_alpha, (int, float)) else (0.4 if "," in qb else 0.8)
        vq = f"embedding:([], alpha: {alpha})"
    else:
        vq = ""

    indeling = []

    if audience and content_type in ("fictie", "beide"):
        indeling += FICTION_MAP.get(audience, [])

    if audience and content_type in ("nonfictie", "beide"):
        indeling += NONFICTION_MAP.get(audience, [])

    fb = _mk_filter_by(indeling_list=indeling, language=language)

    books = COLLECTION_BOOKS_KN if location_kraaiennest else COLLECTION_BOOKS

    return {
        "q": text,
        "collection": books,
        "query_by": qb,
        "vector_query": vq,
        "filter_by": fb,
        "Message": "Ik heb voor je gezocht en deze boeken gevonden",
        "STATUS": "KLAAR",
    }

def _build_faq_params(user_query: str) -> Dict[str, Any]:
    return {
        "q": user_query,
        "collection": COLLECTION_FAQ,
        "query_by": "embedding",
        "vector_query": "embedding:([], alpha: 0.8)",
        "filter_by": "",
        "STATUS": "KLAAR",
    }

TOOL_IMPLS = {
    "build_search_params": _build_search_params,
    "build_faq_params": _build_faq_params,
}
