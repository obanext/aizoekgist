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

    indeling: List[str] = []

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

def _build_agenda_query(
    scenario: str,
    waar: Optional[str] = None,
    leeftijd: Optional[str] = None,
    wanneer: Optional[str] = None,
    type_activiteit: Optional[str] = None,
    agenda_text: Optional[str] = None,
) -> Dict[str, Any]:

    scenario = (scenario or "").upper().strip()

    if waar and waar.lower() in ("oosterdok", "oba oosterdok"):
        waar = "Centrale OBA"

    if scenario == "A":
        base_front = "https://oba.nl/nl/agenda/volledige-agenda"
        qs = []
        if waar:
            qs.append("waar=" + ul.quote_plus(f"/root/OBA/{waar}"))
        if leeftijd:
            qs.append("leeftijd=" + ul.quote_plus(leeftijd))
        if wanneer:
            qs.append("Wanneer=" + wanneer)
        if type_activiteit:
            qs.append("type_activiteit=" + ul.quote_plus(type_activiteit))

        url = base_front + ("?" + "&".join(qs) if qs else "")

        base_api = "https://zoeken.oba.nl/api/v1/search/?q=table:evenementen&refine=true"
        facets = []
        if waar:
            facets.append("facet=waar%28" + ul.quote_plus(f"/root/OBA/{waar}") + "%29")
        if leeftijd:
            facets.append("facet=leeftijd%28" + ul.quote_plus(leeftijd) + "%29")
        if wanneer:
            facets.append("facet=wanneer%28" + wanneer + "%29")
        if type_activiteit:
            facets.append("facet=type_activiteit%28" + ul.quote_plus(type_activiteit) + "%29")

        api = base_api + ("&" + "&".join(facets) if facets else "")

        return {
            "URL": url,
            "API": api,
            "Message": "Ik heb deze activiteiten gevonden",
            "STATUS": "KLAAR",
        }

    return {
        "q": agenda_text or "",
        "collection": COLLECTION_EVENTS,
        "query_by": "embedding",
        "vector_query": "embedding:([], alpha: 0.8)",
        "filter_by": "",
        "Message": "Ik zoek in de agenda",
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
    "build_agenda_query": _build_agenda_query,
    "build_faq_params": _build_faq_params,
}
