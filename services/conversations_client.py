import json
from typing import Any, List, Dict, Optional, Union
from openai import OpenAI
from services.oba_config import TOOLS
from services.oba_tools import (
    TOOL_IMPLS,
    COLLECTION_BOOKS,
    COLLECTION_EVENTS, COLLECTION_BOOKS_KN,
)
from services.oba_helpers import (
    make_envelope,
    typesense_search_books,
    fetch_agenda_results,
    typesense_search_faq,
)
from services.conversations_config import (
    MODEL,
    FASTMODEL,
    SYSTEM,
    NO_RESULTS_MSG,
)
client = OpenAI()

# Per-conversatie cache van laatste resultaten (boeken of agenda)
LAST_RESULTS: dict[str, dict] = {}

def _results_context_block(data: dict, max_items: int = 20) -> str:
    """Bouw een compact SYSTEM-contextblok op basis van laatste resultaten."""
    if not data:
        return ""
    kind = data.get("kind")
    items = (data.get("items") or [])[:max_items]
    lines = []

    if kind == "books":
        for b in items:
            t = (b.get("short_title") or "").strip()
            a = (b.get("auteur") or "").strip()
            d = (b.get("beschrijving") or "").replace("\n", " ").strip()
            if d and len(d) > 500:
                d = d[:500] + "…"
            lines.append(f"- titel: {t}\n  auteur: {a}\n  beschrijving: {d}")

    elif kind == "agenda":
        for it in items:
            title = (it.get("title") or "").strip()
            date  = (it.get("date") or "").strip()
            time  = (it.get("time") or "").strip()
            loc   = (it.get("location") or "").strip()
            summ  = (it.get("summary") or "").replace("\n", " ").strip()
            if summ and len(summ) > 500:
                summ = summ[:500] + "…"
            lines.append(
                f"- titel: {title}\n  datum: {date} {time}\n  locatie: {loc}\n  samenvatting: {summ}"
            )

    if not lines:
        return ""

    return (
        "Dit zijn de laatste zoekresultaten. Als iemand hier iets over vraagt, geef antwoord.\n"
        "ZOEKRESULTATEN\n" + "\n".join(lines) + "\nEINDE_ZOEKRESULTATEN"
    )


def create_conversation() -> str:
    print("Creating conversation...")
    return client.conversations.create().id

def _extract_tool_calls(resp) -> List[Any]:
    """Haal top-level tool/function calls uit een Responses-result."""
    return [
        it
        for it in (getattr(resp, "output", None) or [])
        if getattr(it, "type", "") in ("function_call", "tool_call")
    ]


def _dyn_system_for(conversation_id: str) -> str:
    """Bouw dynamische system-instructies met de laatste resultaten (indien aanwezig)."""
    dyn = SYSTEM
    prev = LAST_RESULTS.get(conversation_id)
    if prev:
        ctx = _results_context_block(prev, max_items=20)
        if ctx:
            dyn = f"{SYSTEM}\n\n{ctx}"
    return dyn


def _handle_tool_result(
    name: str,
    result: Dict[str, Any],
    conversation_id: str,
    user_text: str,
) -> Dict[str, Any]:
    """
    Verwerkt de output van één toolcall:
    - Roept Typesense / Agenda fetchers aan
    - Werkt LAST_RESULTS bij
    - Bouwt de envelope (nog ZONDER ack-tekst)
    Retourneert een dict met:
      { "envelope": envelope_dict, "output_item": {...} }
    """
    # standaard “function_call_output” voor commit naar Responses API
    output_item = {
        "type": "function_call_output",
        "call_id": result.get("_call_id") or "",   # wordt verderop gezet door caller
        "output": json.dumps(result, ensure_ascii=False),
    }

    if name == "build_faq_params":
        faq_results = typesense_search_faq(result)

        # Neem (indien aanwezig) de eerste locatie uit de FAQ-resultaten op in de envelope
        loc: Optional[str] = None
        if faq_results:
            first = faq_results[0] or {}
            loc_val = first.get("location")
            if isinstance(loc_val, str) and loc_val.strip():
                loc = loc_val.strip()

        envelope = make_envelope(
            "faq",
            results=faq_results,
            url=None,
            message=(NO_RESULTS_MSG if not faq_results else None),
            thread_id=conversation_id,
            location=loc,
        )
        return {"envelope": envelope, "output_item": output_item}

    if name in ("build_search_params", "build_compare_params"):
        coll = result.get("collection")
        if coll in (COLLECTION_BOOKS, COLLECTION_BOOKS_KN):
            book_results = typesense_search_books(result)
            if book_results:
                LAST_RESULTS[conversation_id] = {
                    "kind": "books",
                    "items": book_results[:20],  # bevat ppn/titel/auteur/beschrijving
                }
            envelope = make_envelope(
                "collection",
                results=book_results,
                url=None,
                message=(NO_RESULTS_MSG if not book_results else result.get("Message")),
                thread_id=conversation_id,
            )
        else:
            # Valt terug op tekst als er een onverwachte collection is
            envelope = make_envelope(
                "text",
                results=[],
                url=None,
                message=result.get("Message"),
                thread_id=conversation_id,
            )
        return {"envelope": envelope, "output_item": output_item}

    if name == "build_agenda_query":
        if "API" in result and "URL" in result:
            ag_results = fetch_agenda_results(result["API"])
            if ag_results:
                LAST_RESULTS[conversation_id] = {
                    "kind": "agenda",
                    "items": [
                        {
                            "title": it.get("title"),
                            "summary": it.get("summary"),
                            "date": it.get("date") or (it.get("raw_date") or {}).get("start"),
                            "time": it.get("time"),
                            "location": it.get("location"),
                        }
                        for it in ag_results[:20]
                    ],
                }
            envelope = make_envelope(
                "agenda",
                results=ag_results,
                url=result.get("URL"),
                message=(NO_RESULTS_MSG if not ag_results else result.get("Message")),
                thread_id=conversation_id,
            )
        elif result.get("collection") == COLLECTION_EVENTS:
            envelope = make_envelope("agenda", results=[], url=None, message=NO_RESULTS_MSG, thread_id=conversation_id)
        else:
            envelope = make_envelope("agenda", results=[], url=None, message=NO_RESULTS_MSG, thread_id=conversation_id)

        return {"envelope": envelope, "output_item": output_item}

    # Onbekende tool
    envelope = make_envelope("text", results=[], url=None, message="Onbekende tool.", thread_id=conversation_id)
    return {"envelope": envelope, "output_item": output_item}


def _ack_instruction(envelope: Dict[str, Any], user_text: str) -> str:
    """Genereer korte instructie voor de snelle 'ack' generatiemodel-call."""
    resp = envelope.get("response") or {}
    rtype = resp.get("type")
    if rtype == "faq":
        faq_for_prompt = (resp.get("results") or [])[:2]
        return (
            "Formuleer in de taal van de gebruiker een kort en helder antwoord (B1, max 150 woorden) "
            "op basis van de onderstaande FAQ-resultaten. Gebruik alleen de gegeven info, parafraseer. "
            f"Vraag: {user_text}\n"
            f"FAQ-resultaten (JSON): {json.dumps(faq_for_prompt, ensure_ascii=False)}"
        )
    # Default voor collectie/agenda/tekst—frontend toont toch de lijst
    return "Zeg iets als: Ik heb voor je gezocht en deze resultaten gevonden."


def ask_with_tools(conversation_id: str, user_text: str) -> Union[str, Dict[str, Any]]:
    """
    - Geen toolcall  → return tekst-envelop
    - Wel toolcall   → commit outputs + return gevulde envelop (incl. korte ack-tekst)
    """
    # 1) Eerste beurt met tools (system dynamisch met LAST_RESULTS)
    resp = client.responses.create(
        model=MODEL,
        instructions=_dyn_system_for(conversation_id),
        conversation=conversation_id,
        input=user_text,
        tools=TOOLS,
        tool_choice="auto",
    )

    # 2) Geen tools → gewoon tekst
    calls = _extract_tool_calls(resp)
    if not calls:
        text = (resp.output_text or "").strip()
        return make_envelope("text", results=[], url=None, message=text, thread_id=conversation_id)

    # 3) Verwerk alle toolcalls
    envelope: Optional[Dict[str, Any]] = None
    outputs: List[Dict[str, str]] = []

    for call in calls:
        name = call.name
        call_id = getattr(call, "call_id", None) or getattr(call, "id", None)
        args = call.arguments if isinstance(call.arguments, dict) else json.loads(call.arguments or "{}")

        impl = TOOL_IMPLS.get(name)
        result = impl(**args) if impl else {"error": f"Unknown tool: {name}"}
        # geef call_id mee in result, zodat _handle_tool_result het kan loggen
        result["_call_id"] = call_id

        handled = _handle_tool_result(name, result, conversation_id, user_text)
        envelope = handled["envelope"]  # laatste envelope is leidend
        outputs.append(handled["output_item"])

    # 4) Korte ack genereren en invullen als message nog leeg is
    instruction = _ack_instruction(envelope, user_text)
    ack_resp = client.responses.create(
        model=FASTMODEL,
        instructions=instruction,
        conversation=conversation_id,
        tools=[],
        input=outputs,
        tool_choice="none",
    )
    ack_text = (ack_resp.output_text or "").strip() if hasattr(ack_resp, "output_text") else ""

    if envelope and not (envelope.get("response") or {}).get("message"):
        envelope["response"]["message"] = ack_text or envelope["response"].get("message")

    print("message " + (envelope.get("response") or {}).get("message", ""), flush=True)
    return envelope or make_envelope("text", results=[], url=None, message=(ack_text or "Klaar."), thread_id=conversation_id)
