# services/oba_tools.py
import os
import re
import json
import urllib.parse as ul
from typing import Any, Dict, List, Optional

# (optioneel) env overrides; anders veilige defaults
COLLECTION_BOOKS  = os.getenv("COLLECTION_BOOKS",  "obadb30725")
COLLECTION_FAQ    = os.getenv("COLLECTION_FAQ",    "obafaq")
COLLECTION_EVENTS = os.getenv("COLLECTION_EVENTS", "obadbevents")

AGENDA_LOCATIONS = [
    "Centrale OBA", "OBA Banne", "OBA Bijlmer", "OBA Bos en Lommer", "OBA Buitenveldert",
    "OBA CC Amstel", "OBA De Hallen", "OBA Duivendrecht", "OBA Geuzenveld", "OBA IJburg",
    "OBA Mercatorplein", "OBA Molenwijk", "OBA Next Lab Kraaiennest", "OBA Next Lab Sluisbuurt",
    "OBA Olympisch Kwartier", "OBA Osdorp", "OBA Ouderkerk", "OBA Postjesweg", "OBA punt Ganzenhoef",
    "OBA Reigersbos", "OBA Roelof Hartplein", "OBA Slotermeer", "OBA Spaarndammerbuurt",
    "OBA Staatsliedenbuurt", "OBA Van der Pek", "OBA Waterlandplein", "OBA Weesp"
]

AGENDA_AGES = [
    "0 t/m 3 jaar", "4 t/m 12 jaar", "13 t/m 18 jaar",
    "19 t/m 26 jaar", "27 t/m 66 jaar", "67 jaar en ouder"
]

AGENDA_WHEN = [
    "a_today", "a_tomorrow", "b_upcomingweekend", "c_nextweek",
    "d_thismonth", "e_nextmonth", "f_next3month", "g_thisyear", "h_nextyear"
]

AGENDA_TYPES = [
    "Boekenclub", "Expositie", "Film", "Hulp & Ontwikkeling", "Muziek",
    "Ontmoeten", "Overig", "Speciaal", "Talk", "Theater", "Voorlezen", "Workshop"
]

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
        "description": (
            "Zet [AGENDAVRAAG] om naar:\n"
            "Scenario A: Frontend URL + equivalente API-call (als filters uit de vrije tekst te halen zijn).\n"
            "Scenario B: Contextuele zoekvraag (embedding) als filters onduidelijk zijn.\n\n"
            "Herken en map vrijetekst naar filters: Locatie (WAAR), Leeftijdscategorie (LEEFTIJD), "
            "Wanneer (tijdcode), Type activiteit. "
            "Als de gebruiker 'Oosterdok' zegt, gebruik 'Centrale OBA'. "
            "Encodeer waarden exact zoals hieronder; voeg alleen aanwezige filters toe."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scenario": {
                    "type": "string",
                    "enum": ["A", "B"],
                    "description": "Kies 'A' (filters → URL & API) of 'B' (embedding-query)."
                },
                "waar": {
                    "type": "string",
                    "enum": AGENDA_LOCATIONS,
                    "description": "Locatie (WAAR). 'Oosterdok' → 'Centrale OBA'."
                },
                "leeftijd": {
                    "type": "string",
                    "enum": AGENDA_AGES,
                    "description": "Leeftijdscategorie (exacte strings)."
                },
                "wanneer": {
                    "type": "string",
                    "enum": AGENDA_WHEN,
                    "description": "Tijdscode (a_today, b_upcomingweekend, ...)."
                },
                "type_activiteit": {
                    "type": "string",
                    "enum": AGENDA_TYPES,
                    "description": "Activiteitstype."
                },
                "agenda_text": {
                    "type": "string",
                    "description": "Originele vrije vraag. Gebruik dit voor Scenario B."
                }
            },
            "required": ["scenario","agenda_text"],
            "additionalProperties": False
        },
        "strict": False,
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

def _enc_path(path: str) -> str:
    # Spaties → '+', slashes → %2F (zoals in je oorspronkelijke prompt)
    return ul.quote_plus(path, safe="")

def _enc_value(val: str) -> str:
    # Voor losse waardes (leeftijd, type_activiteit)
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

    # Robuust: accepteer 'Oosterdok' als alias (LLM zou al moeten mappen)
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
            "Message": "Agenda-filters gezet. Nog aanpassen?",
            "STATUS": "KLAAR"
        }

    # Scenario B: embedding query
    return {
        "q": agenda_text or "",
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
