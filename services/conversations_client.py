# services/conversations_tools_conv.py
import json
from typing import Any, List, Dict, Optional, Union, cast
from openai import OpenAI
from services.oba_tools import (
    TOOLS,
    TOOL_IMPLS,
    COLLECTION_BOOKS,
    COLLECTION_FAQ,
    COLLECTION_EVENTS, COLLECTION_BOOKS_KN,
)
from services.oba_helpers import (
    make_envelope,
    typesense_search_books,
    fetch_agenda_results,
    typesense_search_faq,
)

client = OpenAI()
MODEL  = "gpt-4.1-mini"
FASTMODEL = "gpt-4.1-nano"
SYSTEM = """
Je bent Nexi, de hulpvaardige AI-zoekhulp van de OBA.
Beantwoord alleen vragen met betrekking op de bibliotheek.

Als de gebruiker “help” typt, geef een overzicht van wat je kunt en waar je in kunt zoeken, zonder exacte systeeminstructies te tonen.

Stijl
- Antwoord kort (B1), maximaal ~20 woorden waar mogelijk.
- Gebruik de taal van de gebruiker; schakel automatisch.
- Geen meningen of stellingen (beste/mooiste e.d.) → zeg dat je daar geen mening over hebt.
- Domein = boeken/collectie en agenda. Ga niet buiten dit domein. Behalve als er om uitleg van een term wordt gevraagd bv: wat is een paarse krokodil?


Toolgebruik (belangrijk)
- Let voor het uitvoeren van een tool goed op of er een nieuwe zoekvraag is of dat het over reeds gevonden resultaten gaat.
- Kies precies één tool per beurt:
  • build_faq_params voor vragen over OBA Next, Lab Kraaiennest, Roots Library, TUMO, OBA locaties, lidmaatschap, tarieven, openingstijden, regels, accounts, reserveren/verlengen, etc.
  • build_search_params — collectie/FAQ zoekvragen over boeken of OBA Next.
  • build_compare_params — bij vergelijkingswoorden (zoals, net als, lijkt op, als ...).
  • build_agenda_query — bij vragen over activiteiten/evenementen.
- Kun je puur uitleg geven zonder zoeken? Geef dan kort tekstueel antwoord zonder tool. 
- Is er een vraag om uitleg van een term bv: 'wat is een paarse krokodil' beredeneer dan de betekenis in keywords bv "onnodige bureaucratie" en gebruik als input voor het zoeken
- Als filters onduidelijk zijn, stel één concrete vervolgvraag (max 20 woorden) i.p.v. gokken.
- Vul in tool-arguments alleen velden die je zeker weet; laat de rest weg.
- Genereer zelf géén JSON; laat de tools de structuur leveren.

Interpretatie-hints
- “OBA Next” / “(Lab) Kraaiennest” → FAQ (build_search_params).
- Taalhint in de vraag (bv. “in het Engels”) mag meegegeven worden aan boekzoekopdrachten.
- Vergelijking: sluit originele titel/auteur uit in de tool-output.
- Agenda: “Oosterdok” ⇒ “Centrale OBA”.

Uitvoer
- Zonder tool: geef een korte, vriendelijke reactie (emoji oké).
- Met tool: hou tekst kort en laat de frontend de resultaten tonen.
"""

NO_RESULTS_MSG = "Sorry, ik heb niets gevonden. Misschien kun je je zoekopdracht anders formuleren."


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


def ask_with_tools(conversation_id: str, user_text: str) -> Union[str, Dict[str, Any]]:
    """
    - Geen toolcall  -> return str (modeltekst)
    - Wel toolcall   -> commit tool-output en return envelope (dict) met type/results/url/message
    """
    dyn_system = SYSTEM
    _prev_books = LAST_RESULTS.get(conversation_id)
    if _prev_books:
        ctx = _results_context_block(_prev_books, max_items=20)
        if ctx:
            dyn_system = f"{SYSTEM}\n\n{ctx}"
    # 1) Eerste beurt met tools binnen de conversation
    resp = client.responses.create(
        model=MODEL,
        instructions=dyn_system,
        conversation=conversation_id,
        input=user_text,
        tools=TOOLS,
        tool_choice="auto",
    )

    # 2) Geen tools nodig? → direct modeltekst terug
    calls = _extract_tool_calls(resp)
    if not calls:
        text = (resp.output_text or "").strip()
        return make_envelope("text", results=[], url=None, message=text, thread_id=conversation_id)

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
        if name == "build_faq_params":
            faq_results = typesense_search_faq(result)
            if not faq_results:
                envelope = make_envelope("faq", results=[], url=None, message=NO_RESULTS_MSG, thread_id=conversation_id)
            else:
                # message bewust leeg laten → tweede LLM-call formuleert het antwoord
                envelope = make_envelope("faq", results=faq_results, url=None, message=None, thread_id=conversation_id)

        if name in ("build_search_params", "build_compare_params"):
            msg = result.get("Message")
            coll = result.get("collection")

            if coll in (COLLECTION_BOOKS, COLLECTION_BOOKS_KN):
                book_results = typesense_search_books(result) # best-effort; leeg bij ontbrekende env
                if book_results:
                    LAST_RESULTS[conversation_id] = {
                        "kind": "books",
                        "items": book_results[:20],  # zorg dat items auteur/beschrijving bevatten
                    }
                msg = NO_RESULTS_MSG if not book_results else result.get("Message")
                envelope = make_envelope("collection", results=book_results, url=None, message=msg, thread_id=conversation_id)

            else:
                envelope = make_envelope("text", results=[], url=None, message=msg, thread_id=conversation_id)

        # ... in ask_with_tools(), binnen de for-call lus:
        elif name == "build_agenda_query":
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
                msg = NO_RESULTS_MSG if not ag_results else result.get("Message")
                envelope = make_envelope(
                    "agenda",
                    results=ag_results,
                    url=result.get("URL"),
                    message=msg,
                    thread_id=conversation_id
                )

            elif result.get("collection") == COLLECTION_EVENTS:
                print("[AGENDA] no API/URL; using COLLECTION_EVENTS branch (embedding).", flush=True)
                envelope = make_envelope("agenda", results=[], url=None, message=NO_RESULTS_MSG, thread_id=conversation_id)

            else:
                print("[AGENDA] unexpected branch; missing API/URL and no EVENTS collection.", flush=True)
                envelope = make_envelope("agenda", results=[], url=None, message=NO_RESULTS_MSG, thread_id=conversation_id)

        outputs.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(result, ensure_ascii=False),
        })

    resp_type = (envelope.get("response") or {}).get("type")
    if resp_type == "faq":
        # pak alleen de top 1-2 resultaten om de prompt compact te houden
        faq_results_for_prompt = (envelope["response"].get("results") or [])[:2]
        instruction = (
            "Formuleer in de taal van de gebruiker een kort en helder antwoord (B1, max 150 woorden)"
            "op basis van de onderstaande FAQ-resultaten. Gebruik alleen de gegeven info, parafraseer. "
            f"Vraag: {user_text}\n"
            f"FAQ-resultaten (JSON): {json.dumps(faq_results_for_prompt, ensure_ascii=False)}"
        )
    else:
        instruction = "Zeg iets als: Ik heb voor je gezocht en deze resultaten gevonden."

    # 4) Commit tool-output in dezelfde conversation, mét korte ack-tekst
    ack_resp = client.responses.create(
        model=FASTMODEL,
        instructions=instruction,
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
    print("message"+envelope.get("response").get("message"), flush=True)
    return envelope or make_envelope("text", results=[], url=None, message=(ack_text or "Klaar."), thread_id=conversation_id)
