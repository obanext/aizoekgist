# services/oba_config.py
"""
Alle constants + TOOLS schema op één plek.
Implementaties staan in services/oba_tools.py (TOOL_IMPLS).
Constants voor de llm specifiek zoals system instructies staan in conversations config
"""

import os
from typing import Any, Dict, List

# === Typesense collections (env overrideable) ===
COLLECTION_BOOKS_KN = os.getenv("COLLECTION_BOOKS_KN", "obadbkraaiennest")
COLLECTION_BOOKS    = os.getenv("COLLECTION_BOOKS",    "obadb30725")
COLLECTION_FAQ      = os.getenv("COLLECTION_FAQ",      "obafaq")
COLLECTION_EVENTS   = os.getenv("COLLECTION_EVENTS",   "obadbevents")

# === Boeken filters ===
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

LANG_HINTS = ["Nederlands", "Engels", "Duits", "Frans", "Spaans", "Turks", "Arabisch"]

# === Agenda filters ===
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

# === TOOLS schema (Responses API) ===
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
                "comparison_query": {
                    "type": "string",
                    "description": "Semantische input (genres/thema's/vergelijkbare auteurs), zonder de originele naam/titel."
                },
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
            "Encodeer waarden exact; voeg alleen aanwezige filters toe."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scenario": {"type": "string", "enum": ["A", "B"],
                             "description": "Kies 'A' (filters → URL & API) of 'B' (embedding-query)."},
                "waar": {"type": "string", "enum": AGENDA_LOCATIONS,
                         "description": "Locatie (WAAR). 'Oosterdok' → 'Centrale OBA'."},
                "leeftijd": {"type": "string", "enum": AGENDA_AGES,
                             "description": "Leeftijdscategorie (exacte strings)."},
                "wanneer": {"type": "string", "enum": AGENDA_WHEN,
                            "description": "Tijdscode (a_today, b_upcomingweekend, ...)."},
                "type_activiteit": {"type": "string", "enum": AGENDA_TYPES,
                                    "description": "Activiteitstype."},
                "agenda_text": {"type": "string",
                                "description": "Originele vrije vraag. Gebruik dit voor Scenario B."}
            },
            "required": ["scenario", "agenda_text"],
            "additionalProperties": False
        },
        "strict": False,
    },
]
