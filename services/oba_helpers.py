# services/oba_helpers.py
import os
import json
import requests
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

# --- ENV ---
TYPESENSE_API_URL = os.getenv("TYPESENSE_API_URL")
TYPESENSE_API_KEY = os.getenv("TYPESENSE_API_KEY")
OBA_API_KEY       = os.getenv("OBA_API_KEY", "")


# --- Message helpers ---
def normalize_message(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw.get("Message") or raw.get("message") or None
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data.get("Message") or data.get("message") or raw
        except Exception:
            return raw
    return str(raw)


def make_envelope(
    resp_type: str,
    results: Optional[List[Dict[str, Any]]] = None,
    url: Optional[str] = None,
    message: Any = None,
    thread_id: Optional[str] = None,
    location: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "response": {
            "type": resp_type,
            "url": url,
            "message": normalize_message(message),
            "results": results or [],
            "location": location,
        },
        "thread_id": thread_id,
    }


# --- Typesense ---
def typesense_search_books(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Best-effort Typesense search (books)."""
    print("Doing a Typesense search...")
    if not TYPESENSE_API_URL or not TYPESENSE_API_KEY:
        return []

    body = {"searches": [{
        "q": params.get("q"),
        "query_by": params.get("query_by"),
        "collection": params.get("collection"),
        "prefix": "false",
        "vector_query": params.get("vector_query"),
        "include_fields": "*",
        "per_page": 15,
        "filter_by": params.get("filter_by"),
    }]}

    print(f"[TS] POST {TYPESENSE_API_URL}")
    print(f"[TS] Request body: {body}", flush=True)

    try:
        r = requests.post(
            TYPESENSE_API_URL,
            json=body,
            headers={"Content-Type": "application/json", "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[TS] Error body: {r.text[:500]}", flush=True)
            return []
        hits = r.json().get("results", [{}])[0].get("hits", [])
        print(f"[TS] Collection={body['searches'][0]['collection']} hits={len(hits)}", flush=True)
        if hits:
            print(f"[TS] First doc keys: {list(hits[0].get('document', {}).keys())}", flush=True)
        out = []
        for h in hits:
            doc = h.get("document") or {}
            out.append({"ppn": doc.get("ppn"), "short_title": doc.get("short_title")})
        return out
    except Exception:
        return []


def typesense_search_faq(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Best-effort Typesense search (FAQ). Returns [{vraag, antwoord, location?}, ...]."""
    if not TYPESENSE_API_URL or not TYPESENSE_API_KEY:
        return []

    body = {"searches": [{
        "q": params.get("q"),
        "query_by": params.get("query_by"),
        "collection": params.get("collection"),
        "prefix": "false",
        "vector_query": params.get("vector_query") or "",
        "include_fields": "*",
        "per_page": 15,
        "filter_by": params.get("filter_by") or "",
    }]}
    try:
        r = requests.post(
            TYPESENSE_API_URL,
            json=body,
            headers={"Content-Type": "application/json", "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        hits = r.json().get("results", [{}])[0].get("hits", [])
        out: List[Dict[str, Any]] = []
        for h in hits:
            doc = h.get("document") or {}
            vraag = doc.get("vraag")
            antwoord = doc.get("antwoord")

            # Locatie kan komma-gescheiden zijn, alleen eerste nodig
            raw_loc = doc.get("locatie")
            first_location: Optional[str] = None
            if isinstance(raw_loc, str) and raw_loc.strip():
                first_location = raw_loc.split(",")[0].strip()

            if vraag or antwoord:
                out.append({
                    "vraag": vraag,
                    "antwoord": antwoord,
                    "location": first_location,
                })
        return out
    except Exception:
        return []


def typesense_search_events(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    
    if not TYPESENSE_API_URL or not TYPESENSE_API_KEY:
        return []

    body = {
        "searches": [{
            "q": params.get("q"),
            "query_by": params.get("query_by"),
            "collection": params.get("collection"),
            "prefix": "false",
            "vector_query": params.get("vector_query") or "",
            "include_fields": "*",
            "per_page": 15,
            "filter_by": params.get("filter_by") or "",
        }]
    }

    try:
        r = requests.post(
            TYPESENSE_API_URL,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY,
            },
            timeout=15,
        )
        if r.status_code != 200:
            return []

        hits = r.json().get("results", [{}])[0].get("hits", [])
        out: List[Dict[str, Any]] = []

        for h in hits:
            doc = h.get("document") or {}

            start = doc.get("starttijd")
            end = doc.get("eindtijd")

         
            title = doc.get("titel") or "Geen titel"
            summary = doc.get("samenvatting") or ""
            cover = doc.get("afbeelding") or ""
            link = doc.get("deeplink") or "#"
            location = doc.get("locatienaam") or doc.get("gebouw") or "Locatie onbekend"
            
            out.append({
                "title": title,
                "summary": summary,
                "cover": cover,
                "link": link,
                "date": start,
                "time": "",
                "location": location,
                "raw_date": {"start": start, "end": end} if (start or end) else None
            })

        return out

    except Exception:
        return []


# --- OBA Agenda ---
def fetch_agenda_results(api_url: str) -> List[Dict[str, Any]]:
    """Fetch agenda XML en geef lijst met {title, cover, link, summary} terug."""
    if not api_url:
        print("[AGENDA][fetch] empty api_url", flush=True)
        return []

    if "authorization=" not in api_url:
        api_url += ("&" if "?" in api_url else "?") + f"authorization={OBA_API_KEY}"

    try:
        print(f"[AGENDA][fetch] GET {api_url}", flush=True)
        r = requests.get(api_url, timeout=15)
        print(f"[AGENDA][fetch] status={r.status_code}", flush=True)
        if r.status_code != 200:
            print(f"[AGENDA][fetch] body(start)={r.text[:400]!r}", flush=True)
            return []

        try:
            root = ET.fromstring(r.text)
        except Exception as e:
            print(f"[AGENDA][fetch] XML parse error: {e}", flush=True)
            print(f"[AGENDA][fetch] body(start)={r.text[:400]!r}", flush=True)
            return []

        nodes = root.findall(".//result")
        print(f"[AGENDA][fetch] result nodes={len(nodes)}", flush=True)

        out: List[Dict[str, Any]] = []
        for res in nodes:
            title = (res.findtext(".//titles/title") or "").strip() or "Geen titel"
            cover = (res.findtext(".//coverimages/coverimage") or "").strip()
            link = (res.findtext(".//custom/evenement/deeplink") or "").strip()
            summary = (res.findtext(".//summaries/summary") or "").strip()
            loc = res.findtext(".//custom/gebeurtenis/locatienaam")

            out.append({
                "title": title,
                "cover": cover,
                "link": link,
                "summary": summary,
                "location": (loc or "").strip()
            })

        return out

    except Exception as e:
        print(f"[AGENDA][fetch] request error: {e}", flush=True)
        return []
