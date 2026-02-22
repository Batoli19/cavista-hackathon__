from __future__ import annotations

from typing import Any, Dict, List


def _value_or_not_captured(value: Any) -> str:
    if value is None:
        return "not captured"
    text = str(value).strip()
    return text if text else "not captured"


def _bullet_lines(items: List[str]) -> str:
    cleaned = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not cleaned:
        return "- not captured"
    return "\n".join([f"- {item}" for item in cleaned])


def _format_vitals(vitals: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if not isinstance(vitals, dict):
        return ["No key measurements were captured."]
    sys_bp = vitals.get("blood_pressure_systolic")
    dia_bp = vitals.get("blood_pressure_diastolic")
    if sys_bp is not None and dia_bp is not None:
        out.append(f"Blood pressure: {sys_bp}/{dia_bp}")
    if vitals.get("heart_rate") is not None:
        out.append(f"Heart rate: {vitals.get('heart_rate')}")
    if vitals.get("temperature") is not None:
        out.append(f"Temperature: {vitals.get('temperature')}")
    if vitals.get("respiratory_rate") is not None:
        out.append(f"Respiratory rate: {vitals.get('respiratory_rate')}")
    if vitals.get("oxygen_saturation") is not None:
        out.append(f"Oxygen saturation: {vitals.get('oxygen_saturation')}%")
    return out or ["No key measurements were captured."]


def _extract_meds(structured_data: Dict[str, Any]) -> List[str]:
    med_history = ((structured_data.get("medical_history") or {}).get("medications") or [])
    med_plan = ((structured_data.get("treatment_plan") or {}).get("medications_prescribed") or [])
    merged: List[str] = []
    for item in med_history + med_plan:
        txt = str(item).strip()
        if txt and txt.lower() not in {m.lower() for m in merged}:
            merged.append(txt)
    return merged


def _extract_tests(structured_data: Dict[str, Any]) -> List[str]:
    tests = ((structured_data.get("treatment_plan") or {}).get("tests_ordered") or [])
    out: List[str] = []
    for item in tests:
        txt = str(item).strip()
        if txt and txt.lower() not in {t.lower() for t in out}:
            out.append(txt)
    return out


def _questions_to_clarify(structured_data: Dict[str, Any]) -> List[str]:
    missing = structured_data.get("missing_data") or []
    prompts = {
        "patient.age": "What is your age?",
        "patient.gender": "What is your sex/gender?",
        "vitals.blood_pressure": "Can your blood pressure be rechecked?",
        "vitals.heart_rate": "Can your heart rate be rechecked?",
        "assessment.primary_diagnosis": "What diagnosis or possible cause was discussed?",
        "medical_history.medications": "Which medicines are you currently taking?",
    }
    questions: List[str] = []
    for key in missing:
        q = prompts.get(str(key).strip())
        if q and q not in questions:
            questions.append(q)
    return questions


def build_patient_doc(structured_data: dict, transcript: str | None, session_id: str | None) -> dict:
    sd = structured_data or {}
    encounter_date = sd.get("encounter_date")
    chief = ((sd.get("chief_complaint") or {}).get("complaint"))
    symptom_names = [str((s or {}).get("name", "")).strip() for s in (sd.get("symptoms") or []) if str((s or {}).get("name", "")).strip()]
    vitals_lines = _format_vitals(sd.get("vitals") or {})
    assessment = ((sd.get("assessment") or {}).get("primary_diagnosis"))
    differentials = (sd.get("assessment") or {}).get("differential_diagnoses") or []
    tests = _extract_tests(sd)
    meds = _extract_meds(sd)
    follow_up = (sd.get("treatment_plan") or {}).get("follow_up")
    red_flags = [str(x).strip() for x in (sd.get("red_flags") or []) if str(x).strip()]
    clarify = _questions_to_clarify(sd)

    concerns: List[str] = []
    if chief:
        concerns.append(f"Main concern discussed: {chief}")
    if symptom_names:
        concerns.append("Symptoms noted: " + ", ".join(symptom_names[:6]))
    if not concerns:
        concerns.append("Main concerns were not clearly captured.")

    assessed_lines: List[str] = []
    if assessment:
        assessed_lines.append(f"Assessment mentioned by clinician: {assessment}")
    else:
        assessed_lines.append("No explicit assessment/possible diagnosis was captured.")
    if differentials:
        assessed_lines.append("Other possibilities discussed: " + ", ".join([str(d) for d in differentials[:5]]))

    meds_lines: List[str] = []
    if meds:
        meds_lines.extend([f"Medicine mentioned: {m}" for m in meds])
        meds_lines.append("Use medicines only as discussed with your clinician.")
    else:
        meds_lines.append("No specific medication details were captured.")

    urgent_generic = [
        "Trouble breathing",
        "Chest pain that is severe, persistent, or spreading",
        "Fainting, severe dizziness, or confusion",
        "Sudden weakness, facial droop, or trouble speaking",
        "Severe sudden headache",
        "Coughing blood or severe bleeding",
    ]
    urgent_items = red_flags + urgent_generic

    title = "Your Visit Summary"
    if encounter_date:
        title = f"Your Visit Summary ({encounter_date})"

    markdown = (
        f"# {title}\n\n"
        "## Main concerns\n"
        f"{_bullet_lines(concerns)}\n\n"
        "## Key measurements\n"
        f"{_bullet_lines(vitals_lines)}\n\n"
        "## What the clinician assessed\n"
        f"{_bullet_lines(assessed_lines)}\n\n"
        "## Tests ordered or planned\n"
        f"{_bullet_lines(tests if tests else ['No tests were explicitly captured.'])}\n\n"
        "## Medicines discussed or started\n"
        f"{_bullet_lines(meds_lines)}\n\n"
        "## What you can do at home\n"
        "- Rest, hydrate, and track your symptoms.\n"
        "- Follow the care plan and instructions you were given during the visit.\n"
        "- Avoid activities that make symptoms significantly worse.\n\n"
        "## Follow-up and monitoring\n"
        f"{_bullet_lines([str(follow_up)] if follow_up else ['Follow up with your clinician as advised or if symptoms persist.'])}\n\n"
        "## When to seek urgent care NOW\n"
        f"{_bullet_lines(urgent_items)}\n\n"
        "## If you are improving\n"
        "- Continue current care steps and monitor symptoms daily.\n"
        "- Keep your follow-up appointment if one was recommended.\n\n"
        "## If you are not improving in 24-48 hours or symptoms worsen\n"
        "- Contact your care team promptly.\n"
        "- Seek urgent evaluation if warning signs appear.\n\n"
        "## Questions to clarify\n"
        f"{_bullet_lines(clarify if clarify else ['No additional clarification items were captured.'])}\n\n"
        "## Disclaimer\n"
        "This is not a final diagnosis or a substitute for medical advice.\n"
    )

    return {
        "doc_title": title,
        "doc_markdown": markdown,
    }
