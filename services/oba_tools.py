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

#Boek filter opties
IND_FICTION = [
    "prentenboeken baby",
    "prentenboeken tot 4 jaar",
    "prentenboeken vanaf 4 jaar",
    "fictie tot 9 jaar",
    "fictie 9 tot 12 jaar",
    "fictie vanaf 12 jaar",
    "fictie vanaf 15 jaar",
    "fictie Volwassenen",
]
IND_NONFICTION = [
    "info tot 9 jaar",
    "info vanaf 9 jaar",
    "info volwassenen",
]
IND_ALL = IND_FICTION + IND_NONFICTION
LANG_HINTS = ["Nederlands", "Engels", "Duits", "Frans", "Spaans", "Turks", "Arabisch"]  # uitbreidbaar

# Agenda filter opties
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
        "description": (
            "Zet [ZOEKVRAAG] om naar Typesense-zoekparameters. "
            "Kies collectie & query_by volgens de regels:\n"
            "- OBA Next / (Lab) Kraaiennest → collection=obafaq, query_by=embedding, alpha=0.8.\n"
            "- Directe titel of auteur → 1 keuze voor query_by (short_title of main_author), géén vector.\n"
            "- Contextuele vraag → embedding (alpha=0.8).\n"
            "- Beide mogelijk → 'embedding, short_title' of 'embedding, main_author' (alpha=0.4).\n"
            "Filters (indeling, taal) alleen zetten als expliciet/ondubbelzinnig in de vraag. Raad niets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_query": {"type": "string", "description": "Zoekvraag in natuurlijke taal."},
                "mode": {
                    "type": "string",
                    "enum": ["faq", "collection"],
                    "description": "Forceer collectie: 'faq' voor OBA Next/locatie-vragen of 'collection' voor boeken."
                },
                "query_by_choice": {
                    "type": "string",
                    "enum": [
                        "short_title", "main_author",
                        "embedding",
                        "embedding, short_title",
                        "embedding, main_author"
                    ],
                    "description": "Optioneel: expliciete keuze voor query_by."
                },
                "vector_alpha": {
                    "type": "number",
                    "description": "Optioneel: alpha voor embedding (0.4 bij mix, 0.8 bij puur embedding)."
                },
                "filters": {
                    "type": "object",
                    "properties": {
                        "indeling": {
                            "type": "array",
                            "items": {"type": "string", "enum": IND_ALL},
                            "description": "0..n indeling-opties; combineer met ||."
                        },
                        "language": {
                            "type": "string",
                            "description": "Taalhint (bv. Nederlands, Engels).",
                            "enum": LANG_HINTS
                        }
                    },
                    "additionalProperties": False
                }
            },
            "required": ["user_query"],
            "additionalProperties": False
        },
        "strict": False,  # velden optioneel laten
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

def _mk_filter_by(indeling_list: Optional[List[str]] = None, language: Optional[str] = None) -> str:
    parts = []
    if indeling_list:
        # "(indeling:=optie1||indeling:=optie2)"
        inner = "||".join([f"indeling:={opt}" for opt in indeling_list if opt])
        if inner:
            parts.append(f"({inner})")
    filt = " && ".join([p for p in parts if p])
    if language:
        # voeg taal altijd als losse AND toe
        # Let op: conform jouw eerdere prompt met spatie voor :=  (language :=Engels)
        suffix = f"&& language :={language}"
        filt = (filt + " " + suffix).strip() if filt else suffix.lstrip("& ").strip()
    return filt

def _looks_author(text: str) -> bool:
    return bool(re.search(r"\b(auteur|schrijver|door|van)\b", text, re.I))

def _looks_title(text: str) -> bool:
    return bool(re.search(r"\btitel\b|\".+\"|\'[^\']+\'", text))

def _build_search_params(
    user_query: str,
    mode: Optional[str] = None,
    query_by_choice: Optional[str] = None,
    vector_alpha: Optional[float] = None,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    text = (user_query or "").strip()
    filters = filters or {}
    indeling_list = filters.get("indeling") if isinstance(filters.get("indeling"), list) else None
    language = filters.get("language")

    # 1) FAQ-detectie of geforceerde mode
    faq_hint = bool(re.search(r"\b(oba\s*next|kraaiennest|lab\s*kraaiennest)\b", text, re.I))
    if (mode == "faq") or (faq_hint and mode is None):
        print("[BOOKS] tool: FAQ branch", flush=True)
        return {
            "q": text,
            "collection": COLLECTION_FAQ,
            "query_by": "embedding",
            "vector_query": "embedding:([], alpha: 0.8)",
            "filter_by": "",
            "Message": "Ik zoek in OBA Next veelgestelde vragen. Wil je verfijnen?",
            "STATUS": "KLAAR"
        }

    # 2) Collection: heuristiek of expliciete keuze van model
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
            # contextueel of gemengd
            qb = "embedding"

    # vector_query op basis van keuze
    if qb.startswith("embedding"):
        # alpha: 0.8 bij puur embedding, 0.4 bij mixed
        alpha = 0.4 if "," in qb else 0.8
        if isinstance(vector_alpha, (int, float)):
            alpha = float(vector_alpha)
        vq = f"embedding:([], alpha: {alpha})"
    else:
        vq = ""

    fb = _mk_filter_by(indeling_list=indeling_list, language=language)

    print(f"[BOOKS] tool: collection qb={qb} vq={'yes' if vq else 'no'} filters={fb!r}", flush=True)
    return {
        "q": text,
        "collection": COLLECTION_BOOKS,
        "query_by": qb,
        "vector_query": vq,
        "filter_by": fb,
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
