"""LLM-driven narration generator that is aware of main moves AND precomputed alternatives.

If OPENAI_API_KEY is not set or the OpenAI lib is unavailable, importing or calling
`from_timeline_llm(...)` will raise, allowing the orchestrator to fall back to the
built-in ScriptGenerator.

Interface:
    from_timeline_llm(timeline_dict, model="gpt-4o-mini") -> List[{"id": str, "text": str}]
"""

from __future__ import annotations

import os
import json
from typing import Dict, List, Any, Optional, Tuple

from .utils.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a calm, ASMR-style chess video narrator.
Style: soothing, concise, confident, never shouty. Prefer plain language over engine jargon.
Each scene gets ONE short line (≈4–10 seconds when spoken).
For alt-scenes, briefly describe the *idea* the engine suggests.
Avoid repeating the obvious when the board already shows it. Keep rhythm gentle.
"""

USER_BRIEF = """You get a summarized TIMELINE with "beats".
Each beat contains:
- A MAIN scene (id like "m17") with: SAN move, optional eval hint (-1..+1), optional pin count.
- Zero or more ALT scenes (ids like "m17_alt2") with: short PV SAN list (2–3 plies), optional cp or mate.

Return JSON array: [{"id": "<sceneId>", "text": "<line>"}] for *every* scene id in input (skip none).
Rules:
- For MAIN scenes: one concise, ASMR-style line reacting to the move (no move list recital), optionally mention eval trend if it’s notable (winning / better / equal).
- For ALT scenes: one short line that frames the idea briefly (e.g., “Another plan: trade on d4 and unwind.”). Do not be technical—focus on intuition.
- Keep it calm, pleasant, lightly descriptive; no hype words.
- Do not include markdown or extra fields.
"""

def _openai_client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError("openai package not installed. `pip install openai`") from e
    return OpenAI(api_key=key)

def _group_beats(timeline: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Group scenes into beats:
      [{"main": {...}, "alts": [{...}, ...]}], and return also a flat list of scene ids in order.
    """
    scenes = timeline.get("scenes", []) or []
    beats: List[Dict[str, Any]] = []
    flat_order: List[str] = []

    current: Dict[str, Any] | None = None
    for s in scenes:
        sid = s.get("id")
        st = s.get("type")
        flat_order.append(sid)

        if st == "main":
            # start a new beat
            if current:
                beats.append(current)
            current = {"main": {
                "id": sid,
                "move": s.get("move"),
                "evalHint": s.get("evalBarTarget"),
                "pins": len(s.get("pins", [])),
                "player": s.get("player"),
                "moveNumber": s.get("moveNumber"),
            }, "alts": []}
        elif st == "alt":
            if current is None:
                # rare, but guard: alt without a preceding main -> make its own beat
                current = {"main": None, "alts": []}
            current["alts"].append({
                "id": sid,
                "pv": s.get("pv", [])[:3],
                "cp": s.get("cp"),
                "mate": s.get("mate"),
                "multipv": s.get("multipv"),
                "label": s.get("label"),
            })
        else:
            # reset scenes get their own simple beat so LLM can still return a line if desired.
            # But per our rules, we do include them (you may keep them minimal like “(beat)” or return empty).
            if current:
                beats.append(current)
                current = None
            beats.append({"main": {"id": sid, "reset": True}, "alts": []})

    if current:
        beats.append(current)

    return beats, flat_order

def _build_user_payload(timeline: Dict[str, Any]) -> Dict[str, Any]:
    beats, flat_order = _group_beats(timeline)
    meta = timeline.get("meta", {})
    return {
        "meta": {
            "white": meta.get("white"),
            "black": meta.get("black"),
            "event": meta.get("event"),
            "date": meta.get("date"),
            "result": meta.get("result"),
            "eco": meta.get("eco"),
        },
        "order": flat_order,
        "beats": beats,
    }

def from_timeline_llm(timeline: Dict[str, Any], model: str = "gpt-4o-mini") -> List[Dict[str, str]]:
    """
    Build narration lines using an LLM, aware of alternative lines precomputed in the timeline.
    Returns [{"id","text"}, ...] in the same order as scenes appear.
    """
    client = _openai_client()
    payload = _build_user_payload(timeline)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_BRIEF},
        {"role": "user", "content": "TIMELINE:\n" + json.dumps(payload, ensure_ascii=False)},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.6,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    try:
        obj = json.loads(content)
    except Exception as e:
        logger.warning(f"LLM returned non-JSON: {content!r} ({e})")
        return []

    # Accept {"lines":[...]} or just an array
    lines = obj.get("lines", obj)
    if not isinstance(lines, list):
        logger.warning(f"Unexpected JSON format from LLM: {obj}")
        return []

    # Normalize and keep only id+text
    out: List[Dict[str, str]] = []
    for it in lines:
        sid = (it.get("id") or "").strip()
        text = (it.get("text") or "").strip()
        if sid and text:
            out.append({"id": sid, "text": text})

    logger.info(f"LLM produced {len(out)} lines.")
    return out
