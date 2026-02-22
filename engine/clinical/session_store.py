from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

STORE_PATH = Path("data") / "sessions.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_store() -> Dict[str, Any]:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        initial = {"sessions": []}
        STORE_PATH.write_text(json.dumps(initial, indent=2), encoding="utf-8")
        return initial
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("sessions"), list):
            return raw
    except Exception:
        pass
    repaired = {"sessions": []}
    STORE_PATH.write_text(json.dumps(repaired, indent=2), encoding="utf-8")
    return repaired


def _save_store(store: Dict[str, Any]) -> None:
    STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def create_session(transcript: str = "", title: str | None = None) -> Dict[str, Any]:
    store = _ensure_store()
    sid = str(uuid.uuid4())[:8]
    now = _now_iso()
    session = {
        "id": sid,
        "title": title or f"Clinical Session {sid}",
        "created_at": now,
        "updated_at": now,
        "transcript": transcript or "",
        "transcript_original": transcript or "",
        "transcript_normalized_en": transcript or "",
        "structured_data": None,
    }
    store["sessions"].append(session)
    _save_store(store)
    return session


def save_session_result(
    session_id: str,
    transcript: str,
    structured_data: Dict[str, Any],
    transcript_original: str | None = None,
    transcript_normalized_en: str | None = None,
) -> Dict[str, Any]:
    store = _ensure_store()
    for session in store["sessions"]:
        if session.get("id") == session_id:
            session["transcript"] = transcript
            if transcript_original is not None:
                session["transcript_original"] = transcript_original
            else:
                session.setdefault("transcript_original", transcript)
            if transcript_normalized_en is not None:
                session["transcript_normalized_en"] = transcript_normalized_en
            else:
                session.setdefault("transcript_normalized_en", transcript)
            session["structured_data"] = structured_data
            session["updated_at"] = _now_iso()
            _save_store(store)
            return session
    raise ValueError(f"Session not found: {session_id}")


def get_session(session_id: str) -> Dict[str, Any] | None:
    store = _ensure_store()
    for session in store["sessions"]:
        if session.get("id") == session_id:
            return session
    return None


def list_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    store = _ensure_store()
    sessions = list(store.get("sessions", []))
    sessions.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return sessions[:limit]
