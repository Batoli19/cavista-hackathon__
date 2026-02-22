CLINICAL_EXTRACTION_PROMPT = """You are a medical AI assistant.

Extract clinical data from the transcript and return ONLY valid JSON using this exact shape:
{
  "encounter_date": "YYYY-MM-DD or null",
  "encounter_type": "inpatient|outpatient|emergency|telehealth|unknown",
  "patient": {
    "patient_id": "string or null",
    "age": "number or null",
    "gender": "male|female|other|unknown",
    "occupation": "string or null"
  },
  "chief_complaint": {
    "complaint": "string",
    "duration": "string or null",
    "severity": "mild|moderate|severe|unknown"
  } or null,
  "symptoms": [{"name": "string", "duration": "string or null", "severity": "mild|moderate|severe or null", "frequency": "string or null", "notes": "string or null"}],
  "vitals": {
    "blood_pressure_systolic": "number or null",
    "blood_pressure_diastolic": "number or null",
    "heart_rate": "number or null",
    "temperature": "number or null",
    "respiratory_rate": "number or null",
    "oxygen_saturation": "number or null",
    "weight": "number or null",
    "height": "number or null",
    "bmi": "number or null"
  },
  "medical_history": {
    "conditions": ["string"],
    "surgeries": ["string"],
    "allergies": ["string"],
    "medications": ["string"],
    "family_history": ["string"],
    "social_history": "string or null"
  },
  "physical_exam": {
    "general_appearance": "string or null",
    "findings": ["string"],
    "abnormalities": ["string"]
  },
  "assessment": {
    "primary_diagnosis": "string or null",
    "differential_diagnoses": ["string"],
    "icd10_codes": ["string"],
    "clinical_impression": "string or null"
  },
  "treatment_plan": {
    "medications_prescribed": ["string"],
    "procedures": ["string"],
    "referrals": ["string"],
    "follow_up": "string or null",
    "patient_instructions": "string or null",
    "tests_ordered": ["string"]
  },
  "clinical_notes": "string or null",
  "red_flags": ["string"],
  "confidence_score": "number between 0 and 1",
  "missing_data": ["string"]
}

Rules:
1) Return JSON only.
2) Never omit keys.
3) Use null for unknown scalar values and [] for unknown arrays.
4) Preserve clinically relevant details if present.
5) Do not invent definitive diagnoses or prescriptions; extract only what is explicitly stated.
6) If uncertain, reflect uncertainty in missing_data and confidence_score.
7) If medication is mentioned, copy exactly as stated; do not invent dosage/frequency unless explicitly stated.
8) Do not add fields outside this schema.

Transcript:
{transcript}
"""


JSON_FIX_PROMPT = """The JSON below failed schema validation.

Return JSON only (no markdown, no explanations).
Fix shape/types only so it validates against the exact schema.
Do not add new fields.
Do not remove required fields.
Keep clinical content faithful to the original and preserve uncertainty as null/[] where needed.

Validation errors:
{errors}

Invalid JSON:
{invalid_json}
"""


TS_TRANSCRIPT_NORMALIZE_PROMPT = """You are a clinical transcript normalization assistant for Botswana.

Task:
1) Detect transcript language: Setswana (`tn`), English (`en`), or `unknown`.
2) If Setswana (or mixed Setswana-English), translate to clear clinical English.
3) Preserve original meaning exactly. Do NOT add facts, diagnoses, medications, doses, tests, or timelines not stated.
4) Keep medication and test names as spoken when possible.
5) Note ambiguities and unclear phrases.
6) Extract key bilingual terms where present.

Return JSON only with EXACT keys:
{
  "language": "tn|en|unknown",
  "confidence": 0.0,
  "original_transcript": "string",
  "normalized_transcript_en": "string",
  "notes": ["string"],
  "key_terms": [{"tn": "string", "en": "string", "type": "symptom|med|test|other"}]
}

Rules:
- Never omit keys.
- Use [] for unknown arrays.
- Use "unknown" for language when unsure.
- If language is en, normalized_transcript_en should be the original meaning in English (can match input).
- Return valid JSON only.

Transcript:
{transcript}
"""
