from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator

from engine.ai_router import route_request

from .prompts import TS_TRANSCRIPT_NORMALIZE_PROMPT


def _fallback_payload(transcript: str) -> Dict[str, Any]:
    return {
        "language": "unknown",
        "confidence": 0.1,
        "original_transcript": transcript,
        "normalized_transcript_en": transcript,
        "notes": ["Normalization fallback used due to provider/JSON failure."],
        "key_terms": [],
    }


def _strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _iter_json_object_candidates(text: str) -> Iterator[str]:
    cleaned = _strip_fences(text)
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for idx, ch in enumerate(cleaned):
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
            continue

        if ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield cleaned[start : idx + 1]
                    start = -1


def _parse_first_valid_dict(text: str) -> Dict[str, Any]:
    errors: list[str] = []
    for candidate in _iter_json_object_candidates(text):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            errors.append(str(exc))
            continue
    if errors:
        raise ValueError(f"No valid JSON object found. Parse errors: {errors[:2]}")
    raise ValueError("No JSON object found in model output.")


def _validate_payload(payload: Dict[str, Any], original: str) -> Dict[str, Any]:
    language = str(payload.get("language") or "unknown").strip().lower()
    if language not in {"tn", "en", "unknown"}:
        language = "unknown"

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.1
    confidence = max(0.0, min(1.0, confidence))

    normalized = str(payload.get("normalized_transcript_en") or "").strip() or original
    notes = payload.get("notes")
    if not isinstance(notes, list):
        notes = []
    notes = [str(x).strip() for x in notes if str(x).strip()]

    key_terms_raw = payload.get("key_terms")
    key_terms: list[Dict[str, str]] = []
    if isinstance(key_terms_raw, list):
        for item in key_terms_raw:
            if not isinstance(item, dict):
                continue
            term_type = str(item.get("type") or "other").strip().lower()
            if term_type not in {"symptom", "med", "test", "other"}:
                term_type = "other"
            key_terms.append(
                {
                    "tn": str(item.get("tn") or "").strip(),
                    "en": str(item.get("en") or "").strip(),
                    "type": term_type,
                }
            )

    return {
        "language": language,
        "confidence": confidence,
        "original_transcript": original,
        "normalized_transcript_en": normalized,
        "notes": notes,
        "key_terms": key_terms,
    }


def normalize_transcript(transcript: str) -> Dict[str, Any]:
    text = str(transcript or "").strip()
    if not text:
        return _fallback_payload("")
    prompt = TS_TRANSCRIPT_NORMALIZE_PROMPT.replace("{transcript}", text)
    try:
        raw = route_request(prompt=prompt, task_type="reasoning")
        payload = _parse_first_valid_dict(raw)
        return _validate_payload(payload, text)
    except Exception:
        return _fallback_payload(text)
