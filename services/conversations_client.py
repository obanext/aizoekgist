# services/conversations_tools_conv.py
import json
from typing import Any, List, Dict, Optional, Union
from openai import OpenAI
from services.oba_tools import (
    TOOLS,
    TOOL_IMPLS,
    COLLECTION_BOOKS,
    COLLECTION_FAQ,
    COLLECTION_EVENTS,
)
from services.oba_helpers import (
    make_envelope,
    typesense_search_books,
    fetch_agenda_results,
)

client = OpenAI()
MODEL  = "gpt-4.1-mini"
FASTMODEL = "gpt-4.1-nano"
SYSTEM = "Je bent Nexi. Antwoord kort (B1), in de taal van de gebruiker."

def create_conversation() -> str:
    return client.conversations.create().id

def _extract_tool_calls(resp) -> List[Any]:
    """Haal top-level tool/function calls uit een Responses-result."""
    return [
        it
        for it in (getattr(resp, "output", None) or [])
        if getattr(it, "type", "") in ("function_call", "tool_call")
    ]


def ask_with_tools(conversation_id: str, user_text: str) -> Union[str, Dict[str, Any]]:
    """
    - Geen toolcall  -> return str (modeltekst)
    - Wel toolcall   -> commit tool-output en return envelope (dict) met type/results/url/message
    """
    # 1) Eerste beurt met tools binnen de conversation
    resp = client.responses.create(
        model=MODEL,
        instructions=SYSTEM,
        conversation=conversation_id,
        input=user_text,
        tools=TOOLS,
        tool_choice="auto",
    )

    # 2) Geen tools nodig? → direct modeltekst terug
    calls = _extract_tool_calls(resp)
    if not calls:
        return (resp.output_text or "").strip()

    # 3) Tools uitvoeren en envelope bepalen
    outputs: List[Dict[str, str]] = []
    envelope: Optional[Dict[str, Any]] = None

    for call in calls:
        name = call.name
        call_id = getattr(call, "call_id", None) or getattr(call, "id", None)
        args = call.arguments if isinstance(call.arguments, dict) else json.loads(call.arguments or "{}")

        impl = TOOL_IMPLS.get(name)
        result = impl(**args) if impl else {"error": f"Unknown tool: {name}"}

        # Bouw envelope op basis van toolresultaat
        if name in ("build_search_params", "build_compare_params"):
            msg = result.get("Message")
            coll = result.get("collection")

            if coll == COLLECTION_FAQ:
                envelope = make_envelope("faq", results=[], url=None, message=msg, thread_id=conversation_id)

            elif coll == COLLECTION_BOOKS:
                book_results = typesense_search_books(result)  # best-effort; leeg bij ontbrekende env
                envelope = make_envelope("collection", results=book_results, url=None, message=msg, thread_id=conversation_id)

            else:
                envelope = make_envelope("text", results=[], url=None, message=msg, thread_id=conversation_id)

        elif name == "build_agenda_query":
            msg = result.get("Message")
            if "API" in result and "URL" in result:
                ag_results = fetch_agenda_results(result["API"])
                envelope = make_envelope("agenda", results=ag_results, url=result.get("URL"), message=msg, thread_id=conversation_id)
            elif result.get("collection") == COLLECTION_EVENTS:
                envelope = make_envelope("agenda", results=[], url=None, message=msg, thread_id=conversation_id)
            else:
                envelope = make_envelope("agenda", results=[], url=None, message=msg, thread_id=conversation_id)

        else:
            envelope = make_envelope("text", results=[], url=None, message="Nog niet ondersteund.", thread_id=conversation_id)

        outputs.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(result, ensure_ascii=False),
        })

    # 4) Commit tool-output in dezelfde conversation, mét korte ack-tekst
    ack_resp = client.responses.create(
        model=FASTMODEL,
        instructions="Zeg iets als: Ik heb voor je gezocht en deze resultaten gevonden.",
        conversation=conversation_id,
        tools=[],            # geen nieuwe tools aanbieden
        input=outputs,       # alleen function_call_output items
        tool_choice="none",  # model mag niets meer starten
    )
    ack_text = (ack_resp.output_text or "").strip() if hasattr(ack_resp, "output_text") else ""

    # Als de envelope nog geen message had, vul 'm met de ack
    if envelope and not envelope["response"].get("message"):
        envelope["response"]["message"] = ack_text or envelope["response"].get("message")

    # 5) Geef envelope terug (of nette fallback)
    return envelope or make_envelope("text", results=[], url=None, message=(ack_text or "Klaar."), thread_id=conversation_id)
