import uuid
from datetime import date, timedelta
from typing import Dict, Any, List, Tuple

from .storage import load_data, save_data
from .ai_planner import generate_plan_ai
from .analytics import diagnose_project

try:
    from engine.clinical.extractor import extract_structured
    from engine.clinical.patient_doc import build_patient_doc
    from engine.clinical.insights import build_clinical_insights
    from engine.clinical.normalize import normalize_transcript
    from engine.clinical.session_store import create_session, get_session, list_sessions, save_session_result
    HAS_CLINICAL = True
except Exception:
    HAS_CLINICAL = False

def _today_iso() -> str:
    return date.today().isoformat()


def create_project(name: str, deadline_iso: str | None = None, description: str = "") -> Dict[str, Any]:
    data = load_data()
    pid = str(uuid.uuid4())[:8]
    project = {
        "id": pid,
        "name": name,
        "description": description,
        "deadline": deadline_iso,
        "created_at": _today_iso(),
        "tasks": [],
    }
    data.setdefault("projects", []).append(project)
    data["active_project_id"] = pid
    save_data(data)
    
    # Index new project for RAG
    # (In a real app, we'd do this async)
    # index_project(project) 
    
    return project


def get_active_project() -> Dict[str, Any] | None:
    data = load_data()
    pid = data.get("active_project_id")
    for p in data.get("projects", []):
        if p.get("id") == pid:
            return p
    return None


def set_active_project(project_id: str) -> Dict[str, Any] | None:
    data = load_data()
    for p in data.get("projects", []):
        if p.get("id") == project_id:
            data["active_project_id"] = project_id
            save_data(data)
            return p
    return None


def generate_plan_basic(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Simple, demo-proof default plan (replace later with AI)
    tasks = [
        {"id": "t1", "name": "Scope & Requirements", "duration_days": 1, "depends_on": [], "status": "pending", "delay_days": 0},
        {"id": "t2", "name": "UI / Design", "duration_days": 1, "depends_on": ["t1"], "status": "pending", "delay_days": 0},
        {"id": "t3", "name": "Core Build (Engine + UI)", "duration_days": 2, "depends_on": ["t2"], "status": "pending", "delay_days": 0},
        {"id": "t4", "name": "Integrations (Voice + Actions)", "duration_days": 1, "depends_on": ["t3"], "status": "pending", "delay_days": 0},
        {"id": "t5", "name": "Testing & Demo Prep", "duration_days": 1, "depends_on": ["t4"], "status": "pending", "delay_days": 0},
    ]
    return tasks


def save_tasks(project_id: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    data = load_data()
    for p in data.get("projects", []):
        if p.get("id") == project_id:
            p["tasks"] = tasks
            save_data(data)
            return p
    return None


def mark_task_done(task_id: str) -> Tuple[bool, str]:
    data = load_data()
    pid = data.get("active_project_id")

    for p in data.get("projects", []):
        if p.get("id") == pid:
            for t in p.get("tasks", []):
                if t.get("id") == task_id:
                    t["status"] = "done"
                    save_data(data)
                    return True, f"Marked {task_id} as done."

    return False, "Task not found."


def delay_task(task_id: str, days: int) -> Tuple[bool, str]:
    data = load_data()
    pid = data.get("active_project_id")

    for p in data.get("projects", []):
        if p.get("id") == pid:
            for t in p.get("tasks", []):
                if t.get("id") == task_id:
                    t["delay_days"] = int(t.get("delay_days", 0)) + int(days)
                    save_data(data)
                    return True, f"Delayed {task_id} by {days} day(s)."

    return False, "Task not found."


def compute_schedule(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Simple dependency scheduling: assumes task list already topologically ordered
    start = date.today()
    schedule: List[Dict[str, Any]] = []
    end_dates: Dict[str, date] = {}

    for t in project.get("tasks", []):
        deps = t.get("depends_on", [])
        base_start = start

        for d in deps:
            if d in end_dates:
                base_start = max(base_start, end_dates[d] + timedelta(days=1))

        duration = int(t.get("duration_days", 1)) + int(t.get("delay_days", 0))
        task_start = base_start
        task_end = task_start + timedelta(days=max(duration - 1, 0))

        end_dates[t["id"]] = task_end
        schedule.append({**t, "start": task_start.isoformat(), "end": task_end.isoformat()})

    return schedule


def get_status(project: Dict[str, Any]) -> Dict[str, Any]:
    schedule = compute_schedule(project)
    if not schedule:
        return {"status": "unknown", "message": "No tasks yet.", "schedule": []}

    final_end = schedule[-1]["end"]
    deadline = project.get("deadline")

    if not deadline:
        return {"status": "ok", "message": f"Estimated finish: {final_end} (no deadline set).", "schedule": schedule}

    if final_end <= deadline:
        return {"status": "on-track", "message": f"On track. Estimated finish {final_end} before deadline {deadline}.", "schedule": schedule}

    return {"status": "off-track", "message": f"Off track. Estimated finish {final_end} after deadline {deadline}.", "schedule": schedule}

def get_project_diagnosis(project_id: str) -> List[str]:
    data = load_data()
    for p in data.get("projects", []):
        if p.get("id") == project_id:
            return diagnose_project(p)
    return ["Project not found."]


def _contract(action: str, ok: bool, data: Any = None, error: str | None = None, meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "action": action,
        "ok": bool(ok),
        "data": data,
        "error": error,
        "meta": meta or {},
    }


def _handle_session_create(params: Dict[str, Any]) -> Dict[str, Any]:
    if not HAS_CLINICAL:
        return _contract("session.create", False, data={"session": None}, error="Clinical module not installed")
    transcript = str(params.get("transcript") or "")
    title = params.get("title")
    session = create_session(transcript=transcript, title=title)
    return _contract("session.create", True, data={"session": session})


def _handle_session_get(params: Dict[str, Any]) -> Dict[str, Any]:
    if not HAS_CLINICAL:
        return _contract("session.get", False, data={"session": None}, error="Clinical module not installed")
    session_id = str(params.get("session_id") or "").strip()
    if not session_id:
        return _contract("session.get", False, data={"session": None}, error="session_id is required")
    session = get_session(session_id)
    if not session:
        return _contract("session.get", False, data={"session": None}, error=f"Session not found: {session_id}")
    return _contract("session.get", True, data={"session": session})


def _handle_session_list(params: Dict[str, Any]) -> Dict[str, Any]:
    if not HAS_CLINICAL:
        return _contract("session.list", False, data={"sessions": []}, error="Clinical module not installed")
    try:
        limit = int(params.get("limit", 20))
    except Exception:
        limit = 20
    sessions = list_sessions(limit=max(1, limit))
    return _contract("session.list", True, data={"sessions": sessions})


def _handle_clinical_extract(params: Dict[str, Any]) -> Dict[str, Any]:
    action = "clinical.extract"
    transcript = str(params.get("transcript") or params.get("text") or params.get("content") or "").strip()
    session_id = str(params.get("session_id") or "").strip() or None
    stable = {
        "session": None,
        "session_id": session_id,
        "transcript": transcript,
        "structured_data": None,
        "red_flags": [],
        "missing_data": [],
    }
    if not HAS_CLINICAL:
        return _contract(action, False, data=stable, error="Clinical module not installed")
    if not transcript:
        return _contract(action, False, data=stable, error="Transcript is required")

    try:
        try:
            translation = normalize_transcript(transcript)
        except Exception:
            translation = {
                "language": "unknown",
                "confidence": 0.1,
                "original_transcript": transcript,
                "normalized_transcript_en": transcript,
                "notes": ["Normalization failed; original transcript used for extraction."],
                "key_terms": [],
            }
        normalized_en = str(translation.get("normalized_transcript_en") or transcript).strip() or transcript
        structured = extract_structured(normalized_en)
        if not session_id:
            session = create_session(transcript=transcript)
            session_id = str(session.get("id", ""))
        saved = save_session_result(
            session_id=session_id,
            transcript=normalized_en,
            structured_data=structured,
            transcript_original=str(translation.get("original_transcript") or transcript),
            transcript_normalized_en=normalized_en,
        )
        payload = {
            "session": saved,
            "session_id": session_id,
            "transcript": transcript,
            "structured_data": structured,
            "red_flags": structured.get("red_flags") or [],
            "missing_data": structured.get("missing_data") or [],
        }
        return _contract(
            action,
            True,
            data=payload,
            meta={
                "transcript_length": len(transcript),
                "payload": {
                    "translation": {
                        "language": translation.get("language", "unknown"),
                        "confidence": translation.get("confidence", 0.1),
                        "notes": translation.get("notes", []),
                        "key_terms": translation.get("key_terms", []),
                        "original_transcript": translation.get("original_transcript", transcript),
                        "normalized_transcript_en": translation.get("normalized_transcript_en", normalized_en),
                    }
                },
            },
        )
    except Exception as exc:
        stable["session_id"] = session_id
        return _contract(action, False, data=stable, error=str(exc))


def _handle_clinical_normalize_transcript(params: Dict[str, Any]) -> Dict[str, Any]:
    action = "clinical.normalize_transcript"
    transcript = str(params.get("transcript") or params.get("text") or params.get("content") or "").strip()
    stable = {
        "language": "unknown",
        "confidence": 0.1,
        "original_transcript": transcript,
        "normalized_transcript_en": transcript,
        "notes": [],
        "key_terms": [],
    }
    if not HAS_CLINICAL:
        return _contract(action, False, data=stable, error="Clinical module not installed")
    if not transcript:
        return _contract(action, False, data=stable, error="Transcript is required")
    try:
        normalized = normalize_transcript(transcript)
        data = {
            "language": normalized.get("language", "unknown"),
            "confidence": normalized.get("confidence", 0.1),
            "original_transcript": normalized.get("original_transcript", transcript),
            "normalized_transcript_en": normalized.get("normalized_transcript_en", transcript),
            "notes": normalized.get("notes", []),
            "key_terms": normalized.get("key_terms", []),
        }
        return _contract(action, True, data=data, meta={})
    except Exception as exc:
        return _contract(action, False, data=stable, error=str(exc))


def _handle_clinical_patient_doc(params: Dict[str, Any]) -> Dict[str, Any]:
    action = "clinical.patient_doc"
    stable = {
        "session_id": None,
        "doc_markdown": "",
        "doc_title": "Your Visit Summary",
        "language": "en",
        "sources": [],
    }
    if not HAS_CLINICAL:
        return _contract(action, False, data=stable, error="Clinical module not installed")

    session_id = str(params.get("session_id") or "").strip() or None
    transcript = params.get("transcript")
    structured_data = params.get("structured_data")

    if session_id:
        session = get_session(session_id)
        if not session:
            stable["session_id"] = session_id
            return _contract(action, False, data=stable, error=f"Session not found: {session_id}")
        transcript = session.get("transcript_normalized_en") or session.get("transcript")
        structured_data = session.get("structured_data")

    transcript = str(transcript or "").strip()
    if not structured_data and transcript:
        extraction = _handle_clinical_extract({"transcript": transcript, "session_id": session_id or ""})
        if not extraction.get("ok"):
            stable["session_id"] = session_id
            return _contract(action, False, data=stable, error=str(extraction.get("error") or "Clinical extraction failed"))
        extracted = extraction.get("data") or {}
        structured_data = extracted.get("structured_data")
        session_id = extracted.get("session_id") or session_id

    if not structured_data:
        stable["session_id"] = session_id
        return _contract(action, False, data=stable, error="Missing required data: provide session_id or transcript")

    try:
        built = build_patient_doc(structured_data=structured_data, transcript=transcript or None, session_id=session_id)
        data = {
            "session_id": session_id,
            "doc_markdown": str(built.get("doc_markdown") or ""),
            "doc_title": str(built.get("doc_title") or "Your Visit Summary"),
            "language": "en",
            "sources": ["structured_data", "transcript"],
        }
        return _contract(action, True, data=data, meta={"template": "deterministic"})
    except Exception as exc:
        stable["session_id"] = session_id
        return _contract(action, False, data=stable, error=str(exc))


def _stable_insights_data(session_id: str | None = None) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "structured_data": {},
        "diagnosis_support": {
            "differential_diagnoses": [],
            "evidence": [],
            "missing_questions": [],
            "risk_tier": "low",
        },
        "actionable_insights": {
            "recommended_next_steps": {
                "Immediate": [],
                "Today": [],
                "Follow-up": [],
            },
            "documentation_gaps": [],
            "safety_net": [],
        },
        "analytics": {
            "summary_cards": [],
            "vitals": [],
            "risk_scores": [],
            "red_flag_summary": {
                "count": 0,
                "items": [],
            },
        },
        "soap_note": {
            "subjective": "",
            "objective": "",
            "assessment": "",
            "plan": "",
        },
    }


def _handle_clinical_insights(params: Dict[str, Any]) -> Dict[str, Any]:
    action = "clinical.insights"
    session_id = str(params.get("session_id") or "").strip() or None
    stable = _stable_insights_data(session_id=session_id)
    if not HAS_CLINICAL:
        return _contract(action, False, data=stable, error="Clinical module not installed")

    transcript = params.get("transcript")
    structured_data = params.get("structured_data")

    if session_id:
        session = get_session(session_id)
        if not session:
            return _contract(action, False, data=stable, error=f"Session not found: {session_id}")
        transcript = session.get("transcript_normalized_en") or session.get("transcript")
        structured_data = session.get("structured_data")

    transcript = str(transcript or "").strip()
    if not structured_data and transcript:
        extraction = _handle_clinical_extract({"transcript": transcript, "session_id": session_id or ""})
        if not extraction.get("ok"):
            return _contract(action, False, data=stable, error=str(extraction.get("error") or "Clinical extraction failed"))
        extracted = extraction.get("data") or {}
        structured_data = extracted.get("structured_data")
        session_id = extracted.get("session_id") or session_id
        stable = _stable_insights_data(session_id=session_id)

    if not structured_data:
        return _contract(action, False, data=stable, error="Missing required data: provide session_id or transcript")

    try:
        insights = build_clinical_insights(structured_data=structured_data, transcript=transcript or None)
        data = {
            "session_id": session_id,
            "structured_data": structured_data,
            "diagnosis_support": insights.get("diagnosis_support") or stable["diagnosis_support"],
            "actionable_insights": insights.get("actionable_insights") or stable["actionable_insights"],
            "analytics": insights.get("analytics") or stable["analytics"],
            "soap_note": insights.get("soap_note") or stable["soap_note"],
        }
        return _contract(action, True, data=data, meta={"mode": "heuristic"})
    except Exception as exc:
        return _contract(action, False, data=stable, error=str(exc))


def execute_action(action: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    params = params or {}
    if action == "session.create":
        return _handle_session_create(params)
    if action == "session.get":
        return _handle_session_get(params)
    if action == "session.list":
        return _handle_session_list(params)
    if action == "clinical.extract":
        return _handle_clinical_extract(params)
    if action == "clinical.normalize_transcript":
        return _handle_clinical_normalize_transcript(params)
    if action == "clinical.patient_doc":
        return _handle_clinical_patient_doc(params)
    if action == "clinical.insights":
        return _handle_clinical_insights(params)
    return _contract(action, False, data=None, error=f"Unknown action: {action}")
