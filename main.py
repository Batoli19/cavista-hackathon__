from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from engine.ai_chat import chat_with_ai
from engine.ai_router import route_action, route_request
from engine.engine import execute_action
from engine.presenter import make_response
from engine.clinical.report_export import generate_clinical_report_docx

_LAST_TRANSCRIPT: str = ""
_LAST_SESSION_ID: str = ""
_LAST_INTENT: str = ""
_PENDING_FOLLOWUP: Dict[str, Any] | None = None

try:
    from voice.voice_io import listen_command, speak
except Exception:
    def speak(text: str) -> None:
        print(f"[TTS] {text}")

    def listen_command() -> str:
        return "VOICE_ERROR: Module not found"


def _normalize_stt_text(text: str) -> tuple[str, List[str]]:
    original = text or ""
    normalized = original
    changes: List[str] = []
    lowered = normalized.lower()

    if "contry" in lowered:
        normalized = re.sub(r"\bcontry\b", "country", normalized, flags=re.IGNORECASE)
        changes.append("contry->country")
    return normalized, changes


def _extract_session_id(text: str) -> str:
    cmd = (text or "").strip()
    patterns = [
        r"\bsession\s+id\s*[:#-]?\s*([a-zA-Z0-9_-]{4,64})\b",
        r"\b(?:get|open|show)\s+session\s+([a-zA-Z0-9_-]{4,64})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cmd, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _extract_transcript(text: str) -> str:
    raw = (text or "").strip()
    prefix_patterns = [
        r"^\s*analyze consult\s*[:\-]?\s*",
        r"^\s*extract clinical data\s*[:\-]?\s*",
        r"^\s*turn this into structured data\s*[:\-]?\s*",
    ]
    cleaned = raw
    for pattern in prefix_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _looks_like_transcript(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    speaker_tags = len(re.findall(r"\b(?:doctor|dr|clinician|provider|patient)\s*:", lowered))
    has_doctor_side = any(tag in lowered for tag in ("doctor:", "dr:", "clinician:", "provider:"))
    has_patient_side = "patient:" in lowered
    has_lines = len([line for line in raw.splitlines() if line.strip()]) >= 2
    return bool(has_doctor_side and has_patient_side and (has_lines or speaker_tags >= 2))


def _looks_greeting(cmd: str) -> bool:
    return cmd in {"hi", "hello", "hey", "yo", "good morning", "good afternoon", "good evening"}


def _classify_intent(text: str) -> str:
    cmd = (text or "").strip().lower()
    if any(phrase in cmd for phrase in ("generate insights", "clinical insights", "dashboard view", "dashboard", "analyze patient")):
        return "clinical_insights"
    if any(phrase in cmd for phrase in ("create patient document", "patient summary", "patient instructions", "discharge instructions")):
        return "clinical_patient_doc"
    if _looks_like_transcript(text):
        return "clinical_extract"
    if cmd == "extract":
        return "clinical_extract"
    action = route_action(cmd)
    if action == "clinical.extract":
        return "clinical_extract"
    if action == "session.create":
        return "session_create"
    if action == "session.get":
        return "session_get"
    if action == "session.list":
        return "session_list"
    if action == "clinical.patient_doc":
        return "clinical_patient_doc"
    if action == "clinical.insights":
        return "clinical_insights"
    return "chat"


def _render_session_summary(session: Dict[str, Any]) -> str:
    session_id = str(session.get("id", "unknown"))
    has_data = bool(session.get("structured_data"))
    status = "structured data ready" if has_data else "transcript only"
    return f"{session_id}: {status}"


def _parse_first_json_dict(text: str) -> Dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for idx, ch in enumerate(raw):
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
                    try:
                        obj = json.loads(raw[start : idx + 1])
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                    start = -1
    return None


def _llm_reasoning_mappings(structured: Dict[str, Any], insights: Dict[str, Any]) -> List[str]:
    evidence = (insights.get("diagnosis_support") or {}).get("evidence") or []
    symptoms = [str((s or {}).get("name") or "").strip().lower() for s in (structured.get("symptoms") or [])]
    symptoms = [s for s in symptoms if s]
    if not evidence:
        return []
    evidence_lines = []
    for e in evidence[:10]:
        finding = str((e or {}).get("finding") or "").strip()
        source = str((e or {}).get("source") or "").strip()
        if finding:
            evidence_lines.append(f"- {finding} | {source}")

    prompt = (
        "You are a clinical reasoning assistant.\n"
        "Use ONLY the provided evidence and symptoms.\n"
        "Do not add new symptoms, medications, diagnoses, or tests.\n"
        "Return JSON only with key 'mappings' as an array of up to 6 strings.\n"
        "Each string format: '<symptom_or_finding> (Source: <source>)'.\n\n"
        f"Symptoms: {json.dumps(symptoms)}\n"
        "Evidence:\n" + "\n".join(evidence_lines)
    )
    try:
        raw = route_request(prompt=prompt, task_type="reasoning")
        parsed = _parse_first_json_dict(raw) or {}
        mappings = parsed.get("mappings")
        if not isinstance(mappings, list):
            raise ValueError("missing mappings list")
        allowed_tokens = set(symptoms)
        for e in evidence[:15]:
            token = str((e or {}).get("finding") or "").strip().lower()
            if token:
                allowed_tokens.add(token)
        out: List[str] = []
        for item in mappings:
            text = str(item).strip()
            if not text:
                continue
            low = text.lower()
            if not any(tok in low for tok in allowed_tokens):
                continue
            out.append(text)
        return out[:6]
    except Exception:
        fallback: List[str] = []
        for e in evidence[:6]:
            finding = str((e or {}).get("finding") or "").strip()
            source = str((e or {}).get("source") or "").strip() or "unknown"
            if finding:
                fallback.append(f"{finding} (Source: {source})")
        return fallback


def _build_extract_reasoning_text(session_id: str, structured: Dict[str, Any], insights: Dict[str, Any]) -> str:
    patient = structured.get("patient") or {}
    age = patient.get("age")
    gender = patient.get("gender", "unknown")
    patient_label = "Unnamed Patient"
    age_label = f"{age}" if age is not None else "Not stated"
    symptoms = structured.get("symptoms") or []
    diagnosis = insights.get("diagnosis_support") or {}
    analytics = insights.get("analytics") or {}
    action = insights.get("actionable_insights") or {}
    soap = insights.get("soap_note") or {}
    red_flags = (analytics.get("red_flag_summary") or {}).get("items") or []
    differentials = diagnosis.get("differential_diagnoses") or []
    gaps = action.get("documentation_gaps") or []
    mappings = _llm_reasoning_mappings(structured, insights)

    lines: List[str] = []
    lines.append(f"Clinical extraction complete for session {session_id}.")
    lines.append("")
    lines.append("### 📋 Extraction Summary")
    lines.append(f"Patient: {patient_label} ({age_label} yo {gender})")
    lines.append("")
    lines.append("Extracted Symptoms:")
    if symptoms:
        for s in symptoms:
            name = str((s or {}).get("name") or "unknown")
            sev = str((s or {}).get("severity") or "unknown")
            lines.append(f"- {name} ({sev})")
    else:
        lines.append("- not captured")
    lines.append("")
    lines.append("Symptom-Condition Mappings:")
    lines.append("LLM Query medical knowledge finding evidence for:")
    if mappings:
        for m in mappings:
            lines.append(f"- {m}")
    else:
        lines.append("- no mapping evidence captured")
    lines.append("")
    lines.append("### 🩺 Clinical Assessment")
    lines.append("Ranked Possible Conditions:")
    if differentials:
        for i, d in enumerate(differentials[:5], start=1):
            lines.append(f"{i}. {d}")
    else:
        lines.append("1. No ranked condition captured.")
    lines.append("")
    lines.append("Red Flags:")
    if red_flags:
        for rf in red_flags:
            lines.append(f"- {rf}")
    else:
        lines.append("- No immediate red flags identified.")
    lines.append("")
    lines.append("### 📝 SOAP Note")
    lines.append("S — Subjective")
    lines.append(str(soap.get("subjective") or "Not captured."))
    lines.append("")
    lines.append("O — Objective")
    lines.append(str(soap.get("objective") or "Not captured."))
    lines.append("")
    lines.append("A — Assessment")
    lines.append(str(soap.get("assessment") or "Not captured."))
    lines.append("")
    lines.append("P — Plan")
    lines.append(str(soap.get("plan") or "Not captured."))
    lines.append("")
    lines.append("### 💡 Clinical Support Suggestions")
    lines.append("Missing Critical Information:")
    if gaps:
        for g in gaps[:8]:
            why = str(g.get("why_it_matters") or "Additional context needed.")
            key = str(g.get("gap") or "unknown")
            lines.append(f"- {why} (Ask if info provided is lacking '{key}')")
    else:
        lines.append("- No critical gaps detected from captured fields.")
    return "\n".join(lines).strip()


def _handle_command_core(text: str, files: List[Any] | None = None) -> Dict[str, Any]:
    global _LAST_TRANSCRIPT, _LAST_SESSION_ID, _LAST_INTENT, _PENDING_FOLLOWUP
    cmd = (text or "").strip().lower()
    files = files or []
    intent = _classify_intent(text)

    if _PENDING_FOLLOWUP and cmd in {"yes", "y", "sure", "ok", "okay"}:
        followup = _PENDING_FOLLOWUP
        _PENDING_FOLLOWUP = None
        if followup.get("type") == "insights_dashboard":
            session_id = str(followup.get("session_id") or _LAST_SESSION_ID)
            result = execute_action("clinical.insights", {"session_id": session_id})
            if not result.get("ok"):
                return make_response(
                    summary="Clinical insights generation failed.",
                    bullets=[str(result.get("error") or "Unknown insights error.")],
                    intent="clinical_insights",
                )
            data = result.get("data") or {}
            diagnosis = data.get("diagnosis_support") or {}
            analytics = data.get("analytics") or {}
            risk_tier = str(diagnosis.get("risk_tier") or "low")
            red_count = int((analytics.get("red_flag_summary") or {}).get("count") or 0)
            gap_count = len((data.get("actionable_insights") or {}).get("documentation_gaps") or [])
            _LAST_INTENT = "clinical_insights"
            resp = make_response(
                summary=f"Clinical insights ready for session {session_id}.",
                bullets=[
                    f"Risk tier: {risk_tier}",
                    f"Red flags: {red_count}",
                    f"Documentation gaps: {gap_count}",
                ],
                intent="clinical_insights",
            )
            resp.setdefault("meta", {}).setdefault("payload", {})["insights"] = data
            file_meta = generate_clinical_report_docx(
                structured_data=data.get("structured_data") or {},
                insights=data,
                session_id=session_id,
            )
            if file_meta:
                resp["files"] = [file_meta]
                show = str(resp.get("show_text") or "")
                if "Download" not in show and "download" not in show:
                    resp["show_text"] = show + "\n- Download: Structured DOCX report is ready."
            return resp
    if _PENDING_FOLLOWUP and cmd in {"no", "n", "nope"}:
        _PENDING_FOLLOWUP = None
        return make_response(summary="Okay.", intent="general")

    if _looks_greeting(cmd):
        return make_response(
            summary="I can extract structured clinical documentation from consult transcripts.",
            bullets=[
                "Say: analyze consult: <transcript>",
                "Say: list sessions",
            ],
            actions=[
                {"label": "Extract Clinical Data", "command": "analyze consult: Doctor: ... Patient: ..."},
                {"label": "List Sessions", "command": "list sessions"},
            ],
            intent="greeting",
            question="Do you want to extract a consult now",
        )

    if "help" in cmd or "what can you do" in cmd:
        return make_response(
            summary="I support clinical session capture and structured extraction.",
            bullets=[
                "Use analyze consult to transform transcript text into structured JSON.",
                "Use session commands to review previous extractions.",
                "This assistant is for documentation support, not final diagnosis or treatment decisions.",
            ],
            intent="help",
            question="Which command do you want to run",
        )

    if intent == "session_create":
        transcript = _extract_transcript(text)
        result = execute_action("session.create", {"transcript": transcript})
        if not result.get("ok"):
            return make_response(summary="Could not create session.", bullets=[str(result.get("error"))], intent="session_create")
        session = (result.get("data") or {}).get("session", {})
        return make_response(
            summary=f'Created clinical session "{session.get("id", "")}".',
            bullets=["You can now run clinical extraction with transcript text."],
            intent="session_create",
            question="Do you want to extract data for this session now",
        )

    if intent == "session_get":
        session_id = _extract_session_id(text)
        if not session_id:
            return make_response(
                summary="Please provide a session id.",
                bullets=["Example: get session 1234abcd"],
                intent="session_get",
            )
        result = execute_action("session.get", {"session_id": session_id})
        if not result.get("ok"):
            return make_response(summary="Session lookup failed.", bullets=[str(result.get("error"))], intent="session_get")
        session = (result.get("data") or {}).get("session", {})
        structured = bool(session.get("structured_data"))
        return make_response(
            summary=f"Loaded session {session.get('id', '')}.",
            bullets=[
                "Structured data is available." if structured else "No structured data saved yet.",
                f"Transcript length: {len(str(session.get('transcript') or ''))} chars",
            ],
            intent="session_get",
        )

    if intent == "session_list":
        result = execute_action("session.list", {})
        if not result.get("ok"):
            return make_response(summary="Could not list sessions.", bullets=[str(result.get("error"))], intent="session_list")
        sessions = (result.get("data") or {}).get("sessions", [])
        if not sessions:
            return make_response(summary="No clinical sessions found.", intent="session_list")
        top = [_render_session_summary(item) for item in sessions[:5]]
        return make_response(
            summary=f"Found {len(sessions)} clinical sessions.",
            bullets=top,
            intent="session_list",
            question="Do you want to open one session id",
        )

    if intent == "clinical_extract":
        transcript = _extract_transcript(text)
        if cmd == "extract":
            transcript = _LAST_TRANSCRIPT.strip()
        if len(transcript) < 20:
            return make_response(
                summary="Please provide a consultation transcript to extract.",
                bullets=[
                    "Example: analyze consult: Doctor: ... Patient: ...",
                    "Or paste raw transcript lines with Doctor: and Patient:.",
                ],
                intent="clinical_extract",
            )
        _LAST_TRANSCRIPT = transcript
        result = execute_action("clinical.extract", {"transcript": transcript})
        if not result.get("ok"):
            return make_response(
                summary="Clinical extraction failed.",
                bullets=[str(result.get("error") or "Unknown extraction error.")],
                intent="clinical_extract",
                question="Do you want to retry with a clearer transcript",
            )
        data = result.get("data") or {}
        structured = data.get("structured_data") or {}
        session = data.get("session") or {}
        _LAST_SESSION_ID = str(session.get("id") or data.get("session_id") or _LAST_SESSION_ID)
        _LAST_INTENT = "clinical_extract"
        _PENDING_FOLLOWUP = {"type": "insights_dashboard", "session_id": _LAST_SESSION_ID}
        insights_result = execute_action("clinical.insights", {"session_id": _LAST_SESSION_ID})
        insights_data = (insights_result.get("data") or {}) if insights_result.get("ok") else {}
        reasoning_text = _build_extract_reasoning_text(
            session_id=str(session.get("id", "")),
            structured=structured,
            insights=insights_data,
        )
        resp = make_response(
            summary=f'Clinical extraction complete for session {session.get("id", "")}.',
            intent="clinical_extract",
            say_text="Clinical extraction is complete.",
            question="Generate insights dashboard now",
        )
        resp["show_text"] = f"{reasoning_text}\n\nGenerate insights dashboard now?"
        file_meta = generate_clinical_report_docx(
            structured_data=structured,
            insights=insights_data if isinstance(insights_data, dict) else {},
            session_id=str(session.get("id") or _LAST_SESSION_ID or "") or None,
        )
        if file_meta:
            resp["files"] = [file_meta]
            show = str(resp.get("show_text") or "")
            if "Download" not in show and "download" not in show:
                resp["show_text"] = show + "\n- Download: Structured DOCX report is ready."
        if insights_data:
            resp.setdefault("meta", {}).setdefault("payload", {})["insights"] = insights_data
        translation = ((result.get("meta") or {}).get("payload") or {}).get("translation")
        if translation:
            resp.setdefault("meta", {}).setdefault("payload", {})["translation"] = translation
        return resp

    if intent == "clinical_insights":
        session_id = _extract_session_id(text) or _LAST_SESSION_ID
        transcript = _extract_transcript(text)
        payload: Dict[str, Any] = {}
        if session_id:
            payload["session_id"] = session_id
        elif transcript and len(transcript) >= 20:
            payload["transcript"] = transcript
        else:
            return make_response(
                summary="Please provide a session id or transcript to generate insights.",
                bullets=[
                    "Example: generate insights for session 1234abcd",
                    "Or: clinical insights: Doctor: ... Patient: ...",
                ],
                intent="clinical_insights",
            )

        result = execute_action("clinical.insights", payload)
        if not result.get("ok"):
            return make_response(
                summary="Clinical insights generation failed.",
                bullets=[str(result.get("error") or "Unknown insights error.")],
                intent="clinical_insights",
            )
        data = result.get("data") or {}
        sid = str(data.get("session_id") or session_id or "")
        if sid:
            _LAST_SESSION_ID = sid
        _LAST_INTENT = "clinical_insights"
        diagnosis = data.get("diagnosis_support") or {}
        analytics = data.get("analytics") or {}
        risk_tier = str(diagnosis.get("risk_tier") or "low")
        diff_count = len(diagnosis.get("differential_diagnoses") or [])
        red_count = int((analytics.get("red_flag_summary") or {}).get("count") or 0)
        resp = make_response(
            summary=f"Clinical insights ready{f' for session {sid}' if sid else ''}.",
            bullets=[
                f"Risk tier: {risk_tier}",
                f"Differential possibilities: {diff_count}",
                f"Red-flag count: {red_count}",
            ],
            intent="clinical_insights",
        )
        resp.setdefault("meta", {}).setdefault("payload", {})["insights"] = data
        file_meta = generate_clinical_report_docx(
            structured_data=data.get("structured_data") or {},
            insights=data,
            session_id=sid or None,
        )
        if file_meta:
            resp["files"] = [file_meta]
            show = str(resp.get("show_text") or "")
            if "Download" not in show and "download" not in show:
                resp["show_text"] = show + "\n- Download: Structured DOCX report is ready."
        return resp

    if intent == "clinical_patient_doc":
        session_id = _extract_session_id(text) or _LAST_SESSION_ID
        transcript = _extract_transcript(text)
        payload: Dict[str, Any] = {}
        if session_id:
            payload["session_id"] = session_id
        elif transcript and len(transcript) >= 20:
            payload["transcript"] = transcript
        else:
            return make_response(
                summary="Please provide a session id or transcript to create a patient document.",
                bullets=[
                    "Example: create patient document for session 1234abcd",
                    "Or: patient summary: Doctor: ... Patient: ...",
                ],
                intent="clinical_patient_doc",
            )

        result = execute_action("clinical.patient_doc", payload)
        if not result.get("ok"):
            return make_response(
                summary="Patient document generation failed.",
                bullets=[str(result.get("error") or "Unknown generation error.")],
                intent="clinical_patient_doc",
            )
        data = result.get("data") or {}
        sid = str(data.get("session_id") or session_id or "")
        doc_markdown = str(data.get("doc_markdown") or "")
        doc_title = str(data.get("doc_title") or "Your Visit Summary")
        if sid:
            _LAST_SESSION_ID = sid
        _LAST_INTENT = "clinical_patient_doc"
        return make_response(
            summary=f"Patient documentation generated{f' for session {sid}' if sid else ''}.",
            bullets=[
                f"Title: {doc_title}",
                "Includes concerns, vitals, follow-up, and urgent-care safety net.",
            ],
            intent="clinical_patient_doc",
            debug={"doc_markdown": doc_markdown, "session_id": sid},
        )

    ai_text = chat_with_ai(text, files=files)
    _LAST_INTENT = "chat"
    return make_response(
        summary=ai_text,
        intent="chat",
        question="Do you want me to extract structured data from a consult transcript",
    )


def handle_command(text: str, files: List[Any] | None = None) -> Dict[str, Any]:
    normalized_text, corrections = _normalize_stt_text(text or "")
    resp = _handle_command_core(normalized_text, files or [])
    if corrections:
        meta = resp.setdefault("meta", {})
        debug = meta.setdefault("debug", {})
        debug["stt_corrections"] = corrections
        debug["normalized_text"] = normalized_text
    return resp


if __name__ == "__main__":
    import sys

    mode = "voice" if len(sys.argv) > 1 and sys.argv[1] == "--voice" else "cli"
    print(f"Assistant ({mode.upper()} mode). Ctrl+C to exit.")
    if mode == "voice":
        speak("Clinical assistant online.")

    while True:
        try:
            if mode == "voice":
                print("Listening...")
                text = listen_command()
                if "VOICE_ERROR" in text:
                    if "Timeout" in text:
                        continue
                    print(text)
                    continue
                if text.lower() in ("exit", "quit"):
                    speak("Goodbye.")
                    break
                result = handle_command(text)
                print(result.get("show_text", ""))
                speak(result.get("say_text", ""))
            else:
                text = input("> ")
                if text.lower() in ("exit", "quit"):
                    break
                result = handle_command(text)
                print(result.get("show_text", ""))
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Error: {exc}")
