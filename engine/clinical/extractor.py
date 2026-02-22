from __future__ import annotations

import json
import re
from typing import Any, Iterator

from engine.ai_router import route_request

from .prompts import CLINICAL_EXTRACTION_PROMPT, JSON_FIX_PROMPT
from .schema import model_to_dict, validate_clinical_data


def _strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _iter_json_object_candidates(text: str) -> Iterator[str]:
    """
    Yield balanced JSON object candidates from free-form model output.
    """
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


def _parse_first_valid_dict(text: str) -> dict[str, Any]:
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


def _call_llm(prompt: str) -> str:
    out = route_request(prompt=prompt, task_type="reasoning")
    lowered = (out or "").lower()
    if "could not reach the main models" in lowered or "ai unavailable" in lowered:
        raise RuntimeError("AI provider unavailable for clinical extraction.")
    return out


def _extract_vitals(transcript: str) -> dict[str, Any]:
    txt = transcript or ""
    vitals: dict[str, Any] = {
        "blood_pressure_systolic": None,
        "blood_pressure_diastolic": None,
        "heart_rate": None,
        "temperature": None,
        "respiratory_rate": None,
        "oxygen_saturation": None,
        "weight": None,
        "height": None,
        "bmi": None,
    }
    bp = re.search(r"\b(?:bp|blood pressure)\s*(?:is|:)?\s*(\d{2,3})\s*/\s*(\d{2,3})\b", txt, flags=re.IGNORECASE)
    if bp:
        vitals["blood_pressure_systolic"] = int(bp.group(1))
        vitals["blood_pressure_diastolic"] = int(bp.group(2))
    hr = re.search(r"\b(?:hr|heart rate|pulse)\s*(?:is|:)?\s*(\d{2,3})\b", txt, flags=re.IGNORECASE)
    if hr:
        vitals["heart_rate"] = int(hr.group(1))
    temp = re.search(r"\b(?:temp|temperature)\s*(?:is|:)?\s*(\d{2,3}(?:\.\d+)?)\b", txt, flags=re.IGNORECASE)
    if temp:
        vitals["temperature"] = float(temp.group(1))
    rr = re.search(r"\b(?:rr|respiratory rate)\s*(?:is|:)?\s*(\d{1,2})\b", txt, flags=re.IGNORECASE)
    if rr:
        vitals["respiratory_rate"] = int(rr.group(1))
    o2 = re.search(r"\b(?:o2|spo2|oxygen saturation|o2 sat)\s*(?:is|:)?\s*(\d{2,3})\s*%?\b", txt, flags=re.IGNORECASE)
    if o2:
        vitals["oxygen_saturation"] = int(o2.group(1))
    return vitals


def _extract_symptoms(transcript: str) -> list[dict[str, Any]]:
    symptom_terms = [
        "chest pain",
        "shortness of breath",
        "dyspnea",
        "sweating",
        "fever",
        "cough",
        "headache",
        "nausea",
        "vomiting",
        "dizziness",
        "fatigue",
        "abdominal pain",
        "sore throat",
        "back pain",
        "left arm pain",
    ]
    text = (transcript or "").lower()
    found: list[dict[str, Any]] = []
    seen = set()
    for term in symptom_terms:
        if term in text and term not in seen:
            found.append(
                {
                    "name": term,
                    "duration": None,
                    "severity": None,
                    "frequency": None,
                    "notes": None,
                }
            )
            seen.add(term)
    return found


def _extract_medications(transcript: str) -> list[str]:
    text = transcript or ""
    meds: list[str] = []
    patterns = [
        r"\b(?:taking|on|started|start|prescribed)\s+([a-zA-Z][a-zA-Z0-9\-\s]{1,60})",
        r"\bmedications?\s*:\s*([^\n\r]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(1).strip(" .,:;")
            if value and value.lower() not in {m.lower() for m in meds}:
                meds.append(value)
    return meds[:5]


def _extract_explicit_diagnosis(transcript: str) -> str | None:
    text = transcript or ""
    patterns = [
        r"\b(?:assessment|diagnosis|impression)\s*:\s*([^\n\r]+)",
        r"\b(?:assessment|diagnosis|impression)\s+is\s+([^\n\r]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .,:;")
            if value:
                return value
    return None


def _extract_tests(transcript: str) -> list[str]:
    known = ["ecg", "ekg", "troponin", "x-ray", "chest x-ray", "ct", "mri", "cbc", "cmp", "ultrasound"]
    text = (transcript or "").lower()
    tests: list[str] = []
    for term in known:
        if term in text and term not in tests:
            tests.append(term.upper() if term in {"ecg", "ekg", "ct", "mri", "cbc", "cmp"} else term.title())
    return tests


def _extract_age_gender(transcript: str) -> tuple[int | None, str]:
    text = transcript or ""
    age = None
    gender = "unknown"
    age_match = re.search(r"\b(\d{1,3})\s*(?:yo|y/o|year old|years old)\b", text, flags=re.IGNORECASE)
    if age_match:
        age = int(age_match.group(1))
    lowered = text.lower()
    if re.search(r"\bmale\b", lowered):
        gender = "male"
    elif re.search(r"\bfemale\b", lowered):
        gender = "female"
    return age, gender


def _derive_red_flags(transcript: str, vitals: dict[str, Any], symptoms: list[dict[str, Any]]) -> list[str]:
    text = (transcript or "").lower()
    names = {s.get("name", "").lower() for s in symptoms}
    flags: list[str] = []
    if "chest pain" in names and ("left arm" in text or "sweating" in text or "shortness of breath" in names):
        flags.append("Chest pain with potential cardiac warning features")
    if vitals.get("oxygen_saturation") is not None and int(vitals["oxygen_saturation"]) < 94:
        flags.append("Low oxygen saturation")
    sys_bp = vitals.get("blood_pressure_systolic")
    if sys_bp is not None and int(sys_bp) >= 180:
        flags.append("Severely elevated systolic blood pressure")
    return flags


def _offline_fallback_extract(transcript: str) -> dict[str, Any]:
    vitals = _extract_vitals(transcript)
    symptoms = _extract_symptoms(transcript)
    medications = _extract_medications(transcript)
    diagnosis = _extract_explicit_diagnosis(transcript)
    tests = _extract_tests(transcript)
    age, gender = _extract_age_gender(transcript)
    red_flags = _derive_red_flags(transcript, vitals, symptoms)

    chief = symptoms[0]["name"] if symptoms else "consult reason not clearly stated"
    missing_data: list[str] = []
    if age is None:
        missing_data.append("patient.age")
    if gender == "unknown":
        missing_data.append("patient.gender")
    if vitals["blood_pressure_systolic"] is None:
        missing_data.append("vitals.blood_pressure")
    if vitals["heart_rate"] is None:
        missing_data.append("vitals.heart_rate")
    if diagnosis is None:
        missing_data.append("assessment.primary_diagnosis")
    if not medications:
        missing_data.append("medical_history.medications")

    payload = {
        "encounter_date": None,
        "encounter_type": "unknown",
        "patient": {
            "patient_id": None,
            "age": age,
            "gender": gender,
            "occupation": None,
        },
        "chief_complaint": {
            "complaint": chief,
            "duration": None,
            "severity": "unknown",
        },
        "symptoms": symptoms,
        "vitals": vitals,
        "medical_history": {
            "conditions": [],
            "surgeries": [],
            "allergies": [],
            "medications": medications,
            "family_history": [],
            "social_history": None,
        },
        "physical_exam": {
            "general_appearance": None,
            "findings": [],
            "abnormalities": [],
        },
        "assessment": {
            "primary_diagnosis": diagnosis,
            "differential_diagnoses": [],
            "icd10_codes": [],
            "clinical_impression": None,
        },
        "treatment_plan": {
            "medications_prescribed": [],
            "procedures": [],
            "referrals": [],
            "follow_up": None,
            "patient_instructions": None,
            "tests_ordered": tests,
        },
        "clinical_notes": None,
        "red_flags": red_flags,
        "confidence_score": 0.35,
        "missing_data": missing_data,
    }

    ok, model, errors = validate_clinical_data(payload)
    if not ok or model is None:
        raise ValueError(f"Offline fallback schema validation failed: {errors}")
    return model_to_dict(model)


def _validate_or_raise(payload: dict[str, Any]) -> dict[str, Any]:
    ok, model, errors = validate_clinical_data(payload)
    if not ok or model is None:
        raise ValueError(f"Clinical extraction validation failed: {errors}")
    return model_to_dict(model)


def extract_structured(transcript: str) -> dict[str, Any]:
    if not (transcript or "").strip():
        raise ValueError("Transcript is required for clinical extraction.")

    first_output = ""
    first_error = ""
    try:
        first_prompt = CLINICAL_EXTRACTION_PROMPT.replace("{transcript}", transcript.strip())
        first_output = _call_llm(first_prompt)
        first_json = _parse_first_valid_dict(first_output)
        return _validate_or_raise(first_json)
    except Exception as first_exc:
        first_error = str(first_exc)

    try:
        fix_prompt = JSON_FIX_PROMPT.format(
            errors=first_error,
            invalid_json=_strip_fences(first_output),
        )
        second_output = _call_llm(fix_prompt)
        second_json = _parse_first_valid_dict(second_output)
        return _validate_or_raise(second_json)
    except Exception as second_exc:
        try:
            return _offline_fallback_extract(transcript)
        except Exception as offline_exc:
            raise ValueError(
                f"Clinical extraction failed after model parse/fix and offline fallback. "
                f"Fix error: {second_exc}. Offline error: {offline_exc}"
            )
