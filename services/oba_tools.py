# services/oba_tools.py
import os
import re
import urllib.parse as ul
from typing import Any, Dict, List, Optional

# (optioneel) env overrides; anders veilige defaults
COLLECTION_BOOKS_KN = os.getenv("COLLECTION_BOOKS_KN", "obadbkraaiennest")
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
        "name": "build_faq_params",
        "description": (
            "Zet een FAQ- of OBA Next-vraag om naar Typesense-FAQ parameters. "
            "Gebruik embedding (alpha=0.8), geen filters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_query": {
                    "type": "string",
                    "description": "FAQ-vraag in natuurlijke taal (OBA Next, locaties, lidmaatschap, tarieven, etc.)."
                }
            },
            "required": ["user_query"],
            "additionalProperties": False
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "build_search_params",
        "description": (
            "Zet [ZOEKVRAAG] voor boeken om naar Typesense-zoekparameters.\n"
            "- Directe titel of auteur → 1 keuze voor query_by (short_title of main_author), géén vector.\n"
            "- Contextuele vraag → embedding (alpha=0.8).\n"
            "- Beide mogelijk → 'embedding, short_title' of 'embedding, main_author' (alpha=0.4).\n"
            "Filters (indeling, taal) alleen zetten als expliciet/ondubbelzinnig in de vraag. Raad niets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_query": {"type": "string", "description": "Zoekvraag in natuurlijke taal."},
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
                "location_kraaiennest": {
                    "type": "boolean",
                    "description": "Zet op true als de gebruiker expliciet Kraaiennest vraagt."
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
        "strict": False,
    },
    # vervang het huidige build_compare_params item in TOOLS door dit:

    {
        "type": "function",
        "name": "build_compare_params",
        "description": (
            "Zet [VERGELIJKINGSVRAAG] om naar Typesense-zoekparameters voor vergelijkbare boeken. "
            "Transformeer titel/auteur naar semantische trefwoorden (genres, thema’s, toon, doelgroep) "
            "en/of vergelijkbare auteurs. Neem de originele titel/auteur NIET op in 'q'. "
            "Vul 'original' en 'mode' zodat wij die kunnen uitsluiten via filters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "comparison_query": {"type": "string",
                                     "description": "Semantische input (genres/thema's/vergelijkbare auteurs), zonder de originele naam/titel."},
                "original": {"type": "string", "description": "De exacte titel of auteur die moet worden uitgesloten."},
                "mode": {
                    "type": "string",
                    "enum": ["author", "title", "other"],
                    "description": "Waar vergelijkt de gebruiker op? Bepaalt welk veld we uitsluiten."
                },
                "vector_alpha": {"type": "number",
                                 "description": "Optioneel: alpha voor embedding (0.4 bij author-mix, 0.8 standaard)."},
                "location_kraaiennest": {
                    "type": "boolean",
                    "description": "Zet op true als de gebruiker expliciet Kraaiennest vraagt."
                },
                "filters": {
                    "type": "object",
                    "properties": {
                        "indeling": {
                            "type": "array",
                            "items": {"type": "string", "enum": IND_ALL},
                            "description": "0..n indelingen; combineer met ||."
                        },
                        "language": {
                            "type": "string",
                            "enum": LANG_HINTS,
                            "description": "Taalhint (bv. Nederlands, Engels)."
                        }
                    },
                    "additionalProperties": False
                }
            },
            "required": ["comparison_query"],
            "additionalProperties": False
        },
        "strict": False,
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
    query_by_choice: Optional[str] = None,
    vector_alpha: Optional[float] = None,
    location_kraaiennest: Optional[bool] = False,
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    text = (user_query or "").strip()
    filters = filters or {}
    indeling_list = filters.get("indeling") if isinstance(filters.get("indeling"), list) else None
    language = filters.get("language")
    print(f"kraaiennest?{location_kraaiennest}")
    # Alleen boekenlogica (FAQ is nu aparte tool build_faq_params)
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

    print(f"[BOOKS] tool: collection qb={qb} vq={'yes' if vq else 'no'} filters={fb!r}", flush=True)
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
    """Zet een string veilig tussen dubbele quotes voor Typesense filter_by."""
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
    """
    LLM-gedreven:
    - comparison_query: LLM levert semantische beschrijving (genres/thema's/vergelijkbare auteurs), ZONDER originele naam/titel.
    - original: exacte auteur of titel om uit te sluiten.
    - mode: 'author' | 'title' | 'other' (bepaalt welk veld we uitsluiten en rankingmix).
    """
    q_text = (comparison_query or "").strip()
    orig   = (original or "").strip()
    mode   = (mode or "other").strip().lower()

    # 1) Basisfilters (indeling/taal)
    filters = filters or {}
    indeling_list = filters.get("indeling") if isinstance(filters.get("indeling"), list) else None
    language = filters.get("language")
    fb_base = _mk_filter_by(indeling_list=indeling_list, language=language)

    books = COLLECTION_BOOKS_KN if location_kraaiennest else COLLECTION_BOOKS

    # 2) Ranking & veldkeuze
    if mode == "author":
        query_by = "main_author, embedding"   # mix: wat dichter op auteurssignatuur
        default_alpha = 0.4
        excl_field = "main_author"
    else:
        # 'title' en 'other' → puur embedding werkt vaak het best
        query_by = "embedding"
        default_alpha = 0.8
        excl_field = "short_title" if mode == "title" else "short_title"

    alpha = float(vector_alpha) if isinstance(vector_alpha, (int, float)) else default_alpha
    vector = f"embedding:([], alpha: {alpha})"

    # 3) Exclusie bouwen met Typesense-syntax (!=)
    parts = []
    if fb_base:
        parts.append(fb_base)

    if orig:
        parts.append(f'{excl_field}:!= {_ts_quote(orig)}')

    filter_by = " && ".join(p for p in parts if p)

    print(f"[COMPARE] tool mode={mode} alpha={alpha} exclude={orig!r} filter_by={filter_by!r}", flush=True)

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
            "Message": "Ik heb deze activiteiten in de agenda gevonden",
            "STATUS": "KLAAR"
        }

    # Scenario B: embedding query
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
        "Message": "Ik zoek in OBA Next veelgestelde vragen. Wil je verfijnen?", # wordt geleegd doet niks
        "STATUS": "KLAAR",
    }


# ---- Dispatcher tabel ----
TOOL_IMPLS = {
    "build_faq_params":     _build_faq_params,
    "build_search_params":  _build_search_params,
    "build_compare_params": _build_compare_params,
    "build_agenda_query":   _build_agenda_query,
}
