"""
Implementaties van de tool-functies.
Het TOOLS-schema en alle constants staan in services/oba_config.py
"""

import re
import urllib.parse as ul
from typing import Any, Dict, List, Optional

from services.oba_config import (
    COLLECTION_BOOKS,
    COLLECTION_BOOKS_KN,
    COLLECTION_FAQ,
    COLLECTION_EVENTS,
)

def _mk_filter_by(indeling_list: Optional[List[str]] = None, language: Optional[str] = None) -> str:
    parts = []
    if indeling_list:
        inner = "||".join([f"indeling:={opt}" for opt in indeling_list if opt])
        if inner:
            parts.append(f"({inner})")
    filt = " && ".join([p for p in parts if p])
    if language:
        suffix = f"&& language :={language}"  # let op: spatie voor := is bewust
        filt = (filt + " " + suffix).strip() if filt else suffix.lstrip("& ").strip()
    return filt

def _looks_author(text: str) -> bool:
    return bool(re.search(r"\b(auteur|schrijver|door|van)\b", text, re.I))

def _looks_title(text: str) -> bool:
    return bool(re.search(r"\btitel\b|\".+\"|\'[^\']+\'", text))

def _build_search_params(
    user_query: str,
    query_by_choice: Optional[str] = None,
    vector_alpha: Optional[float] = None,
    location_kraaiennest: Optional[bool] = False,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    text = (user_query or "").strip()
    filters = filters or {}
    indeling_list = filters.get("indeling") if isinstance(filters.get("indeling"), list) else None
    language = filters.get("language")

    looks_author = _looks_author(text)
    looks_title  = _looks_title(text)

    if query_by_choice:
        qb = query_by_choice
    else:
        if looks_author and not looks_title:
            qb = "main_author"
        elif looks_title and not looks_author:
            qb = "short_title"
        else:
            qb = "embedding"

    if qb.startswith("embedding"):
        alpha = 0.4 if "," in qb else 0.8
        if isinstance(vector_alpha, (int, float)):
            alpha = float(vector_alpha)
        vq = f"embedding:([], alpha: {alpha})"
    else:
        vq = ""

    books = COLLECTION_BOOKS_KN if location_kraaiennest else COLLECTION_BOOKS
    fb = _mk_filter_by(indeling_list=indeling_list, language=language)

    print(f"[BOOKS] tool: collection={books} qb={qb} vq={'yes' if vq else 'no'} filters={fb!r}", flush=True)
    return {
        "q": text,
        "collection": books,
        "query_by": qb,
        "vector_query": vq,
        "filter_by": fb,
        "Message": "Ik heb voor je gezocht en deze boeken voor je gevonden",
        "STATUS": "KLAAR"
    }

def _ts_quote(val: str) -> str:
    v = (val or "").strip().replace('"', '\\"')
    return f'"{v}"'

def _build_compare_params(
    comparison_query: str,
    original: Optional[str] = None,
    mode: Optional[str] = None,
    vector_alpha: Optional[float] = None,
    location_kraaiennest: Optional[bool] = False,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    q_text = (comparison_query or "").strip()
    orig   = (original or "").strip()
    mode   = (mode or "other").strip().lower()

    filters = filters or {}
    indeling_list = filters.get("indeling") if isinstance(filters.get("indeling"), list) else None
    language = filters.get("language")
    fb_base = _mk_filter_by(indeling_list=indeling_list, language=language)

    books = COLLECTION_BOOKS_KN if location_kraaiennest else COLLECTION_BOOKS

    if mode == "author":
        query_by = "main_author, embedding"
        default_alpha = 0.4
        excl_field = "main_author"
    else:
        query_by = "embedding"
        default_alpha = 0.8
        excl_field = "short_title" if mode == "title" else "short_title"

    alpha = float(vector_alpha) if isinstance(vector_alpha, (int, float)) else default_alpha
    vector = f"embedding:([], alpha: {alpha})"

    parts = []
    if fb_base:
        parts.append(fb_base)
    if orig:
        parts.append(f'{excl_field}:!={_ts_quote(orig)}')  # zonder extra spatie

    filter_by = " && ".join(p for p in parts if p)

    print(f"[COMPARE] tool collection={books} mode={mode} alpha={alpha} exclude={orig!r} filter_by={filter_by!r}", flush=True)

    return {
        "q": q_text,
        "collection": books,
        "query_by": query_by,
        "vector_query": vector,
        "filter_by": filter_by,
        "Message": "Ik zocht iets vergelijkbaars, is dit wat je zocht?",
        "STATUS": "KLAAR",
    }

def _enc_path(path: str) -> str:
    return ul.quote_plus(path, safe="")

def _enc_value(val: str) -> str:
    return ul.quote_plus(val, safe="")

def _build_agenda_query(
    scenario: str,
    waar: Optional[str] = None,
    leeftijd: Optional[str] = None,
    wanneer: Optional[str] = None,
    type_activiteit: Optional[str] = None,
    agenda_text: Optional[str] = None
) -> Dict[str, Any]:
    scenario = (scenario or "").strip().upper()

    if waar and waar.lower().strip() in ("oosterdok", "oba oosterdok", "centrale oba"):
        waar = "Centrale OBA"

    if scenario == "A":
        base_front = "https://oba.nl/nl/agenda/volledige-agenda"
        qs = []
        if waar:
            qs.append("waar=" + _enc_path(f"/root/OBA/{waar}"))
        if leeftijd:
            qs.append("leeftijd=" + _enc_value(leeftijd))
        if wanneer:
            qs.append("Wanneer=" + wanneer)
        if type_activiteit:
            qs.append("type_activiteit=" + _enc_value(type_activiteit))

        url = base_front + ("?" + "&".join(qs) if qs else "")

        base_api = "https://zoeken.oba.nl/api/v1/search/?q=table:evenementen&refine=true"
        facets = []
        if waar:
            facets.append("facet=waar%28" + _enc_path(f"/root/OBA/{waar}") + "%29")
        if leeftijd:
            facets.append("facet=leeftijd%28" + _enc_value(leeftijd) + "%29")
        if wanneer:
            facets.append("facet=wanneer%28" + wanneer + "%29")
        if type_activiteit:
            facets.append("facet=type_activiteit%28" + _enc_value(type_activiteit) + "%29")

        api = base_api + ("&" + "&".join(facets) if facets else "")

        return {
            "URL": url,
            "API": api,
            "Message": "Ik heb deze activiteiten in de agenda gevonden",
            "STATUS": "KLAAR"
        }

    return {
        "q": agenda_text or "",
        "collection": COLLECTION_EVENTS,
        "query_by": "embedding",
        "vector_query": "embedding:([], alpha: 0.8)",
        "filter_by": "",
        "Message": "Ik zoek contextueel in de agenda",
        "STATUS": "KLAAR"
    }

def _build_faq_params(user_query: str) -> Dict[str, Any]:
    text = (user_query or "").strip()
    print("[FAQ] tool executed", flush=True)
    return {
        "q": text,
        "collection": COLLECTION_FAQ,
        "query_by": "embedding",
        "vector_query": "embedding:([], alpha: 0.8)",
        "filter_by": "",
        "Message": "Ik zoek in OBA Next veelgestelde vragen. Wil je verfijnen?",
        "STATUS": "KLAAR",
    }

TOOL_IMPLS = {
    "build_faq_params":     _build_faq_params,
    "build_search_params":  _build_search_params,
    "build_compare_params": _build_compare_params,
    "build_agenda_query":   _build_agenda_query,
}
