import os
from typing import Any, Dict, List

COLLECTION_BOOKS_KN = os.getenv("COLLECTION_BOOKS_KN", "obadbkraaiennest")
COLLECTION_BOOKS    = os.getenv("COLLECTION_BOOKS",    "obadb30725")
COLLECTION_FAQ      = os.getenv("COLLECTION_FAQ",      "obafaq")
COLLECTION_EVENTS   = os.getenv("COLLECTION_EVENTS",   "obadbevents")

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

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "build_faq_params",
        "parameters": {
            "type": "object",
            "properties": {
                "user_query": {"type": "string"}
            },
            "required": ["user_query"],
            "additionalProperties": False
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "build_search_params",
        "parameters": {
            "type": "object",
            "properties": {
                "user_query": {"type": "string"},
                "query_by_choice": {
                    "type": "string",
                    "enum": [
                        "short_title",
                        "main_author",
                        "embedding",
                        "embedding, short_title",
                        "embedding, main_author"
                    ]
                },
                "vector_alpha": {"type": "number"},
                "location_kraaiennest": {"type": "boolean"},
                "audience": {
                    "type": "string",
                    "enum": [
                        "baby",
                        "peuter",
                        "kleuter",
                        "kind",
                        "jeugd",
                        "oudere_jeugd",
                        "volwassen"
                    ]
                },
                "content_type": {
                    "type": "string",
                    "enum": ["fictie", "nonfictie", "beide"]
                },
                "filters": {
                    "type": "object",
                    "properties": {
                        "language": {
                            "type": "string",
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
        "parameters": {
            "type": "object",
            "properties": {
                "comparison_query": {"type": "string"},
                "original": {"type": "string"},
                "mode": {"type": "string"},
                "vector_alpha": {"type": "number"},
                "location_kraaiennest": {"type": "boolean"},
                "filters": {"type": "object"}
            },
            "required": ["comparison_query"],
            "additionalProperties": False
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "build_agenda_query",
        "parameters": {
            "type": "object",
            "properties": {
                "scenario": {"type": "string"},
                "waar": {"type": "string"},
                "leeftijd": {"type": "string"},
                "wanneer": {"type": "string"},
                "type_activiteit": {"type": "string"},
                "agenda_text": {"type": "string"}
            },
            "required": ["scenario", "agenda_text"],
            "additionalProperties": False
        },
        "strict": False,
    },
]
