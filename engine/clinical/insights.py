from __future__ import annotations

import re
from typing import Any, Dict, List


def _symptom_names(structured_data: Dict[str, Any], transcript: str | None = None) -> List[str]:
    out: List[str] = []
    for item in (structured_data.get("symptoms") or []):
        name = str((item or {}).get("name") or "").strip().lower()
        if name and name not in out:
            out.append(name)
    chief = str(((structured_data.get("chief_complaint") or {}).get("complaint")) or "").strip().lower()
    if chief:
        for token in [
            "chest pain",
            "shortness of breath",
            "dyspnea",
            "fever",
            "cough",
            "headache",
            "nausea",
            "vomiting",
            "dizziness",
            "fatigue",
            "sore throat",
            "body aches",
            "abdominal pain",
        ]:
            if token in chief and token not in out:
                out.append(token)
    text = (transcript or "").lower()
    if text:
        for token in [
            "chest pain",
            "shortness of breath",
            "dyspnea",
            "fever",
            "cough",
            "headache",
            "nausea",
            "vomiting",
            "dizziness",
            "fatigue",
            "sore throat",
            "body aches",
            "abdominal pain",
            "left arm pain",
            "sweating",
        ]:
            if token in text and token not in out:
                out.append(token)
    return out


def _vital_value(vitals: Dict[str, Any], key: str) -> float | int | None:
    value = vitals.get(key)
    if value is None:
        return None
    try:
        return float(value) if "." in str(value) else int(value)
    except Exception:
        return None


def _extract_vitals_from_text(transcript: str | None) -> Dict[str, Any]:
    txt = transcript or ""
    out: Dict[str, Any] = {}
    bp = re.search(r"\b(?:bp|blood pressure)\s*(?:is|:)?\s*(\d{2,3})\s*/\s*(\d{2,3})\b", txt, flags=re.IGNORECASE)
    if bp:
        out["blood_pressure_systolic"] = int(bp.group(1))
        out["blood_pressure_diastolic"] = int(bp.group(2))
    hr = re.search(r"\b(?:hr|heart rate|pulse)\s*(?:is|:)?\s*(\d{2,3})\b", txt, flags=re.IGNORECASE)
    if hr:
        out["heart_rate"] = int(hr.group(1))
    temp = re.search(r"\b(?:temp|temperature|fever)\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)\b", txt, flags=re.IGNORECASE)
    if temp:
        out["temperature"] = float(temp.group(1))
    rr = re.search(r"\b(?:rr|respiratory rate)\s*(?:is|:)?\s*(\d{1,2})\b", txt, flags=re.IGNORECASE)
    if rr:
        out["respiratory_rate"] = int(rr.group(1))
    o2 = re.search(r"\b(?:o2|spo2|oxygen saturation|o2 sat)\s*(?:is|:)?\s*(\d{2,3})\s*%?\b", txt, flags=re.IGNORECASE)
    if o2:
        out["oxygen_saturation"] = int(o2.group(1))
    return out


def _merged_vitals(structured_data: Dict[str, Any], transcript: str | None = None) -> Dict[str, Any]:
    vitals = dict(structured_data.get("vitals") or {})
    from_text = _extract_vitals_from_text(transcript)
    for key, value in from_text.items():
        if vitals.get(key) is None:
            vitals[key] = value
    return vitals


def _vitals_analytics(structured_data: Dict[str, Any], transcript: str | None = None) -> List[Dict[str, Any]]:
    vitals = _merged_vitals(structured_data, transcript)
    specs = [
        ("Systolic BP", "blood_pressure_systolic", "mmHg", 90, 120),
        ("Diastolic BP", "blood_pressure_diastolic", "mmHg", 60, 80),
        ("Heart Rate", "heart_rate", "bpm", 60, 100),
        ("Temperature", "temperature", "C", 36.1, 37.2),
        ("Respiratory Rate", "respiratory_rate", "breaths/min", 12, 20),
        ("Oxygen Saturation", "oxygen_saturation", "%", 95, 100),
    ]
    out: List[Dict[str, Any]] = []
    for name, key, unit, low, high in specs:
        value = _vital_value(vitals, key)
        if value is None:
            status = "not_captured"
        elif value < low:
            status = "low"
        elif value > high:
            status = "high"
        else:
            status = "normal"
        out.append(
            {
                "name": name,
                "value": value,
                "unit": unit,
                "status": status,
                "min": low,
                "max": high,
            }
        )
    return out


def _build_evidence(structured_data: Dict[str, Any], transcript: str | None = None) -> List[Dict[str, str]]:
    evidence: List[Dict[str, str]] = []
    chief = ((structured_data.get("chief_complaint") or {}).get("complaint"))
    if chief:
        evidence.append({"finding": str(chief), "source": "chief_complaint.complaint"})
    for item in (structured_data.get("symptoms") or []):
        name = str((item or {}).get("name") or "").strip().lower()
        sev = str((item or {}).get("severity") or "").strip().lower()
        if name:
            finding = f"{name} ({sev})" if sev and sev != "unknown" else name
            evidence.append({"finding": finding, "source": "symptoms[].name/severity"})
    for symptom in _symptom_names(structured_data, transcript)[:6]:
        evidence.append({"finding": symptom, "source": "symptoms[].name"})
    vitals = _merged_vitals(structured_data, transcript)
    if vitals.get("blood_pressure_systolic") is not None and vitals.get("blood_pressure_diastolic") is not None:
        evidence.append(
            {
                "finding": f"BP {vitals.get('blood_pressure_systolic')}/{vitals.get('blood_pressure_diastolic')}",
                "source": "vitals",
            }
        )
    if vitals.get("heart_rate") is not None:
        evidence.append({"finding": f"HR {vitals.get('heart_rate')}", "source": "vitals.heart_rate"})
    if vitals.get("oxygen_saturation") is not None:
        evidence.append({"finding": f"SpO2 {vitals.get('oxygen_saturation')}%", "source": "vitals.oxygen_saturation"})
    return evidence


def _differentials(structured_data: Dict[str, Any], transcript: str | None = None) -> List[str]:
    symptoms = set(_symptom_names(structured_data, transcript))
    vitals = _merged_vitals(structured_data, transcript)
    out: List[str] = []
    provided = (structured_data.get("assessment") or {}).get("differential_diagnoses") or []
    for item in provided:
        txt = str(item).strip()
        if txt:
            out.append(f"{txt} (possible)")

    bp_sys = _vital_value(vitals, "blood_pressure_systolic")
    o2 = _vital_value(vitals, "oxygen_saturation")
    hr = _vital_value(vitals, "heart_rate")

    if "chest pain" in symptoms:
        out.append("Acute coronary syndrome (possible)")
    if "shortness of breath" in symptoms or "dyspnea" in symptoms:
        out.append("Cardiopulmonary cause of dyspnea (possible)")
    if ("cough" in symptoms and "fever" in symptoms) or (o2 is not None and o2 < 94):
        out.append("Respiratory infection or lower respiratory process (possible)")
    if "headache" in symptoms and bp_sys is not None and bp_sys >= 180:
        out.append("Hypertensive urgency/emergency syndrome (possible)")
    if ("abdominal pain" in symptoms and "nausea" in symptoms) or "vomiting" in symptoms:
        out.append("Gastrointestinal inflammatory process (possible)")
    if hr is not None and hr > 110 and "fever" in symptoms:
        out.append("Systemic infection response (possible)")

    uniq: List[str] = []
    seen = set()
    for item in out:
        key = item.lower()
        if key not in seen:
            uniq.append(item)
            seen.add(key)
    return uniq[:5]


def _missing_questions(structured_data: Dict[str, Any]) -> List[str]:
    prompts = {
        "patient.age": "What is the patient's age?",
        "patient.gender": "What is the patient's sex/gender?",
        "vitals.blood_pressure": "Can blood pressure be measured/rechecked?",
        "vitals.heart_rate": "Can heart rate be measured/rechecked?",
        "assessment.primary_diagnosis": "What assessment was explicitly documented?",
        "medical_history.medications": "What current medications were reported?",
    }
    out: List[str] = []
    for key in (structured_data.get("missing_data") or []):
        prompt = prompts.get(str(key).strip())
        if prompt and prompt not in out:
            out.append(prompt)
    if not out:
        out.append("No major missing questions were detected from structured fields.")
    return out


def _documentation_gaps(structured_data: Dict[str, Any]) -> List[Dict[str, str]]:
    severity_map = {
        "vitals.blood_pressure": ("high", "Blood pressure is required to assess urgency and cardiovascular risk."),
        "vitals.heart_rate": ("medium", "Heart rate supports stability assessment and triage decisions."),
        "assessment.primary_diagnosis": ("high", "Assessment framing is needed to align next steps and follow-up."),
        "medical_history.medications": ("medium", "Medication history affects safety and interaction risk."),
        "patient.age": ("medium", "Age affects baseline risk stratification."),
        "patient.gender": ("low", "Sex/gender can affect differential interpretation."),
    }
    out: List[Dict[str, str]] = []
    for key in (structured_data.get("missing_data") or []):
        gap = str(key).strip()
        severity, why = severity_map.get(gap, ("low", "Additional context may improve decision support quality."))
        out.append({"gap": gap, "severity": severity, "why_it_matters": why})
    return out


def _symptom_severity_score(structured_data: Dict[str, Any], transcript: str | None = None) -> tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []
    for item in (structured_data.get("symptoms") or []):
        sev = str((item or {}).get("severity") or "").strip().lower()
        name = str((item or {}).get("name") or "").strip().lower()
        if not name:
            continue
        if sev in {"severe", "high"}:
            score += 0.2
            reasons.append(f"severe {name}")
        elif sev in {"moderate", "medium"}:
            score += 0.1
            reasons.append(f"moderate {name}")
        elif sev in {"mild", "low"}:
            score += 0.03
            reasons.append(f"mild {name}")
    text = (transcript or "").lower()
    if any(w in text for w in ["severe pain", "worst", "can't breathe", "crushing", "fainting"]):
        score += 0.2
        reasons.append("severe symptom language in transcript")
    return min(1.0, score), reasons


def _risk_scores(structured_data: Dict[str, Any], evidence: List[Dict[str, str]], transcript: str | None = None) -> List[Dict[str, Any]]:
    symptoms = set(_symptom_names(structured_data, transcript))
    vitals = _merged_vitals(structured_data, transcript)
    red_flags = structured_data.get("red_flags") or []
    bp_sys = _vital_value(vitals, "blood_pressure_systolic")
    hr = _vital_value(vitals, "heart_rate")
    o2 = _vital_value(vitals, "oxygen_saturation")
    symptom_severity, reasons_s = _symptom_severity_score(structured_data, transcript)

    instability = 0.15
    reasons_i: List[str] = []
    if bp_sys is not None and bp_sys >= 180:
        instability += 0.35
        reasons_i.append(f"systolic BP {int(bp_sys)}")
    if hr is not None and hr >= 120:
        instability += 0.2
        reasons_i.append(f"heart rate {int(hr)}")
    if o2 is not None and o2 < 94:
        instability += 0.3
        reasons_i.append(f"SpO2 {int(o2)}%")
    if red_flags:
        instability += 0.2
        reasons_i.append(f"{len(red_flags)} red-flag finding(s)")
    if symptom_severity > 0:
        instability += min(0.25, symptom_severity)
        reasons_i.extend(reasons_s[:2])
    instability = min(1.0, instability)

    cardio = 0.1
    reasons_c: List[str] = []
    if "chest pain" in symptoms:
        cardio += 0.4
        reasons_c.append("chest pain")
    if "shortness of breath" in symptoms or "dyspnea" in symptoms:
        cardio += 0.25
        reasons_c.append("dyspnea/shortness of breath")
    if bp_sys is not None and bp_sys >= 160:
        cardio += 0.15
        reasons_c.append(f"elevated BP {int(bp_sys)}")
    cardio = min(1.0, cardio)

    gaps = len(structured_data.get("missing_data") or [])
    completeness = min(1.0, round(gaps / 10.0, 2))
    reasons_d = [f"{gaps} documented gap(s)"]

    def _band(value: float) -> str:
        if value >= 0.67:
            return "high"
        if value >= 0.34:
            return "medium"
        return "low"

    return [
        {
            "name": "physiologic_instability",
            "value": round(instability, 2),
            "band": _band(instability),
            "explanation": "Based on " + ", ".join(reasons_i or ["captured vitals and red-flag review"]) + ".",
        },
        {
            "name": "cardiorespiratory_concern",
            "value": round(cardio, 2),
            "band": _band(cardio),
            "explanation": "Based on " + ", ".join(reasons_c or ["captured symptom profile"]) + ".",
        },
        {
            "name": "documentation_completeness_risk",
            "value": round(completeness, 2),
            "band": _band(completeness),
            "explanation": "Based on " + ", ".join(reasons_d) + ".",
        },
        {
            "name": "symptom_severity_signal",
            "value": round(min(1.0, symptom_severity), 2),
            "band": _band(min(1.0, symptom_severity)),
            "explanation": "Based on " + ", ".join(reasons_s or ["captured symptom severity"]) + ".",
        },
    ]


def _risk_tier(risk_scores: List[Dict[str, Any]], red_flags: List[str]) -> str:
    max_score = max([float(item.get("value", 0.0)) for item in risk_scores] + [0.0])
    if red_flags or max_score >= 0.67:
        return "high"
    if max_score >= 0.34:
        return "medium"
    return "low"


def _variant_for_tier(tier: str) -> str:
    if tier == "high":
        return "danger"
    if tier == "medium":
        return "warning"
    return "success"


def _recommended_steps(risk_tier: str, structured_data: Dict[str, Any]) -> Dict[str, List[str]]:
    tests = (structured_data.get("treatment_plan") or {}).get("tests_ordered") or []
    follow_up = (structured_data.get("treatment_plan") or {}).get("follow_up")
    immediate: List[str] = []
    today: List[str] = []
    follow: List[str] = []

    if risk_tier == "high":
        immediate.append("Escalate to urgent in-person clinical evaluation now.")
        immediate.append("Monitor for worsening red-flag symptoms continuously.")
    else:
        immediate.append("Reassess current symptoms and vital sign trends promptly.")

    if tests:
        today.append("Complete ordered tests: " + ", ".join([str(t) for t in tests[:5]]))
    else:
        today.append("Confirm whether further diagnostic testing is needed today.")
    today.append("Close key documentation gaps before handoff.")

    if follow_up:
        follow.append(str(follow_up))
    else:
        follow.append("Arrange follow-up within 24-72 hours based on symptom progression.")
    follow.append("Return sooner if symptoms worsen or new warning signs appear.")

    return {"Immediate": immediate, "Today": today, "Follow-up": follow}


def _safety_net_items(structured_data: Dict[str, Any]) -> List[str]:
    items = [str(x).strip() for x in (structured_data.get("red_flags") or []) if str(x).strip()]
    generic = [
        "Seek urgent care now for severe chest pain or trouble breathing.",
        "Seek urgent care now for fainting, sudden weakness, confusion, or severe headache.",
        "Seek urgent care now for coughing blood, persistent vomiting, or severe bleeding.",
    ]
    for line in generic:
        if line not in items:
            items.append(line)
    return items


def _generate_soap_note(structured_data: Dict[str, Any], insights: Dict[str, Any]) -> Dict[str, str]:
    """
    Build compact clinical reasoning narrative in SOAP format.
    """
    vitals = (insights.get("analytics") or {}).get("vitals") or []
    vital_lines = [f"{v.get('name')}: {v.get('value')} {v.get('unit')}".strip() for v in vitals if v.get("value") is not None]

    symptoms = [s.get("name") for s in (structured_data.get("symptoms") or []) if s.get("name")]
    chief = (structured_data.get("chief_complaint") or {}).get("complaint")

    subjective_parts: List[str] = []
    if chief:
        subjective_parts.append(f"Chief complaint: {chief}")
    if symptoms:
        subjective_parts.append("Reported symptoms: " + ", ".join([str(s) for s in symptoms]))

    objective_parts = vital_lines if vital_lines else ["Vitals not captured."]
    assessment_parts = (insights.get("diagnosis_support") or {}).get("differential_diagnoses") or []

    plan_parts: List[str] = []
    next_steps = (insights.get("actionable_insights") or {}).get("recommended_next_steps") or {}
    for category, steps in next_steps.items():
        if steps:
            plan_parts.append(f"{category}: " + "; ".join([str(x) for x in steps]))

    return {
        "subjective": "\n".join(subjective_parts) if subjective_parts else "No subjective data captured.",
        "objective": "\n".join(objective_parts),
        "assessment": "\n".join([str(x) for x in assessment_parts]) if assessment_parts else "Assessment pending further evaluation.",
        "plan": "\n".join(plan_parts) if plan_parts else "Plan pending further evaluation.",
    }


def build_clinical_insights(structured_data: Dict[str, Any], transcript: str | None = None) -> Dict[str, Any]:
    data = structured_data or {}
    evidence = _build_evidence(data, transcript)
    differentials = _differentials(data, transcript)
    risk_scores = _risk_scores(data, evidence, transcript)
    red_flags = [str(x).strip() for x in (data.get("red_flags") or []) if str(x).strip()]
    tier = _risk_tier(risk_scores, red_flags)
    gaps = _documentation_gaps(data)
    confidence = float(data.get("confidence_score") if data.get("confidence_score") is not None else 0.5)
    confidence = max(0.0, min(1.0, confidence))
    gap_count = len(gaps)
    summary_cards = [
        {"label": "Risk Tier", "value": tier, "variant": _variant_for_tier(tier)},
        {
            "label": "Red Flags",
            "value": len(red_flags),
            "variant": "danger" if len(red_flags) > 0 else "success",
        },
        {
            "label": "Documentation Gaps",
            "value": gap_count,
            "variant": "danger" if gap_count >= 5 else "warning" if gap_count >= 2 else "success",
        },
        {
            "label": "Confidence",
            "value": round(confidence, 2),
            "variant": "warning" if confidence < 0.5 else "info",
        },
    ]

    insights = {
        "diagnosis_support": {
            "differential_diagnoses": differentials,
            "evidence": evidence,
            "missing_questions": _missing_questions(data),
            "risk_tier": tier,
        },
        "actionable_insights": {
            "recommended_next_steps": _recommended_steps(tier, data),
            "documentation_gaps": gaps,
            "safety_net": _safety_net_items(data),
        },
        "analytics": {
            "summary_cards": summary_cards,
            "vitals": _vitals_analytics(data, transcript),
            "risk_scores": risk_scores,
            "red_flag_summary": {
                "count": len(red_flags),
                "items": red_flags,
            },
        },
    }
    insights["soap_note"] = _generate_soap_note(data, insights)
    return insights
