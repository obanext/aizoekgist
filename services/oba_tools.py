# services/oba_tools.py
import os
import re
import json
from typing import Any, Dict, List

# (optioneel) env overrides; anders veilige defaults
COLLECTION_BOOKS  = os.getenv("COLLECTION_BOOKS",  "obadb30725")
COLLECTION_FAQ    = os.getenv("COLLECTION_FAQ",    "obafaq")
COLLECTION_EVENTS = os.getenv("COLLECTION_EVENTS", "obadbevents")

# ---- Toolschema's (Responses API) ----
TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "build_search_params",
        "description": "Zet [ZOEKVRAAG] om naar Typesense-zoekparameters (collectie/embedding/filters).",
        "parameters": {
            "type": "object",
            "properties": {
                "user_query": { "type": "string", "description": "Zoekvraag in natuurlijke taal." }
            },
            "required": ["user_query"],
            "additionalProperties": False
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "build_compare_params",
        "description": "Zet [VERGELIJKINGSVRAAG] om naar Typesense-zoekparameters met uitsluiting van originele titel/auteur.",
        "parameters": {
            "type": "object",
            "properties": {
                "comparison_query": { "type": "string", "description": "Vergelijkingsvraag in natuurlijke taal." }
            },
            "required": ["comparison_query"],
            "additionalProperties": False
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "build_agenda_query",
        "description": "Zet [AGENDAVRAAG] om naar (A) frontend URL + API-call of (B) embedding-query voor events.",
        "parameters": {
            "type": "object",
            "properties": {
                "agenda_text": { "type": "string", "description": "Agenda-vraag in natuurlijke taal." }
            },
            "required": ["agenda_text"],
            "additionalProperties": False
        },
        "strict": True,
    },
]

# ---- Eenvoudige implementaties ----

def _build_search_params(user_query: str) -> Dict[str, Any]:
    text = (user_query or "").strip()
    # OBA Next / Kraaiennest → FAQ
    if re.search(r"\b(oba\s*next|kraaiennest|lab\s*kraaiennest)\b", text, re.I):
        print("executed a tool for books")
        return {
            "q": text,
            "collection": COLLECTION_FAQ,
            "query_by": "embedding",
            "vector_query": "embedding:([], alpha: 0.8)",
            "filter_by": "",
            "Message": "Ik zoek in OBA Next veelgestelde vragen. Wil je verfijnen?",
            "STATUS": "KLAAR"
        }

    # Heel simpel: titel of auteur hints
    looks_author = bool(re.search(r"\b(auteur|schrijver|door|van)\b", text, re.I))
    looks_title  = bool(re.search(r"\btitel\b|\".+\"|\'[^\']+\'", text))

    if looks_author and not looks_title:
        query_by, vector = "main_author", ""
    elif looks_title and not looks_author:
        query_by, vector = "short_title", ""
    else:
        # contextueel/mix
        query_by, vector = "embedding", "embedding:([], alpha: 0.8)"
    print("executed a tool for books")
    return {
        "q": text,
        "collection": COLLECTION_BOOKS,
        "query_by": query_by,
        "vector_query": vector,
        "filter_by": "",
        "Message": "Zoekopdracht klaar. Wil je doelgroep of taal toevoegen?",
        "STATUS": "KLAAR"
    }

def _build_compare_params(comparison_query: str) -> Dict[str, Any]:
    text = (comparison_query or "").strip()
    m = re.search(r"(zoals|net als|lijkt op|als)\s+([^\.,;]+)", text, re.I)
    original = (m.group(2).strip(" '\"") if m else "")

    # standaard: vergelijk op embedding + sluit titel uit
    query_by  = "embedding"
    vector    = "embedding:([], alpha: 0.8)"
    excl      = f"&&short_title:! {original}" if original else ""

    # als 'auteur' genoemd wordt, dan main_author + uitsluiten auteur
    if re.search(r"\b(auteur|schrijver)\b", text, re.I):
        query_by = "main_author, embedding"
        vector   = "embedding:([], alpha: 0.4)"
        excl     = f"&&main_author:! {original}" if original else ""

    # verwijder het vergelijkingswoord uit q
    q_clean = re.sub(r"(zoals|net als|lijkt op|als)\s+", "", text, flags=re.I)

    print("executed a compare tool for books")

    return {
        "q": q_clean,
        "collection": COLLECTION_BOOKS,
        "query_by": query_by,
        "vector_query": vector,
        "filter_by": excl.lstrip("&"),
        "Message": "Ik zocht iets dat erop lijkt. Wil je doelgroep/taal erbij?",
        "STATUS": "KLAAR"
    }

def _build_agenda_query(agenda_text: str) -> Dict[str, Any]:
    t = (agenda_text or "").strip().lower()

    # mini-detectie locatie/wanneer/type (superkort gehouden)
    loc = "Centrale OBA" if "oosterdok" in t else None
    when = "b_upcomingweekend" if "weekend" in t else ("d_thismonth" if "deze maand" in t else None)
    typ = "Workshop" if "workshop" in t else None

    # A: als we iets herkennen → bouw URL + API
    if loc or when or typ:
        import urllib.parse as ul
        base_front = "https://oba.nl/nl/agenda/volledige-agenda"
        qs = []
        if loc:  qs.append("waar=" + ul.quote(f"/root/OBA/{loc}".replace(" ", "+")))
        if when: qs.append("Wanneer=" + when)
        if typ:  qs.append("type_activiteit=" + ul.quote(typ))
        url = base_front + ("?" + "&".join(qs) if qs else "")

        base_api = "https://zoeken.oba.nl/api/v1/search/?q=table:evenementen&refine=true"
        facets = []
        if loc:  facets.append("facet=waar%28" + ul.quote(f"/root/OBA/{loc}".replace(" ", "+")) + "%29")
        if when: facets.append("facet=wanneer%28" + when + "%29")
        if typ:  facets.append("facet=type_activiteit%28" + ul.quote(typ) + "%29")
        api = base_api + ("&" + "&".join(facets) if facets else "")
        print("executed a tool for agenda")
        return {"URL": url, "API": api, "Message": "Agenda-filters gezet. Nog aanpassen?", "STATUS": "KLAAR"}
    print("executed a tool for agenda")
    # B: anders: embedding query voor events
    return {
        "q": agenda_text,
        "collection": COLLECTION_EVENTS,
        "query_by": "embedding",
        "vector_query": "embedding:([], alpha: 0.8)",
        "filter_by": "",
        "Message": "Ik zoek contextueel in de agenda. Locatie/datum toevoegen?",
        "STATUS": "KLAAR"
    }

# ---- Dispatcher tabel ----
TOOL_IMPLS = {
    "build_search_params":  _build_search_params,
    "build_compare_params": _build_compare_params,
    "build_agenda_query":   _build_agenda_query,
}
