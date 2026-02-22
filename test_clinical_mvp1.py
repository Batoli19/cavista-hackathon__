import os
import sys
import unittest

sys.path.append(os.getcwd())

from engine.engine import execute_action
import engine.engine as engine_module
from engine.clinical.schema import validate_clinical_data
import engine.clinical.extractor as extractor_module
from main import handle_command


EXTRACT_STABLE_KEYS = {
    "session",
    "session_id",
    "transcript",
    "structured_data",
    "red_flags",
    "missing_data",
}


class TestClinicalMvp1Flow(unittest.TestCase):
    def test_clinical_normalize_transcript_setswana_sample(self):
        transcript = (
            "Ngaka: Dumela mma, o tla ka eng gompieno?\n"
            "Molwetse: Ke na le botlhoko mo tlhogong, le mogote mo mmeleng."
        )
        result = execute_action("clinical.normalize_transcript", {"transcript": transcript})
        self.assertTrue({"action", "ok", "data", "error", "meta"}.issubset(result.keys()))
        self.assertEqual(result.get("action"), "clinical.normalize_transcript")
        self.assertTrue(result.get("ok"))
        data = result.get("data") or {}
        self.assertIn(data.get("language"), {"tn", "en", "unknown"})
        self.assertGreaterEqual(float(data.get("confidence", 0.0)), 0.0)
        self.assertTrue(str(data.get("normalized_transcript_en") or "").strip())

    def test_raw_transcript_routes_to_clinical_extract_intent(self):
        transcript = "Doctor: What brings you in?\nPatient: Chest pain for two hours."
        result = handle_command(transcript)
        self.assertEqual(result.get("meta", {}).get("intent"), "clinical_extract")

    def test_clinical_extract_contract_keys(self):
        result = execute_action("clinical.extract", {"transcript": "Doctor: hello\nPatient: headache"})
        self.assertTrue({"action", "ok", "data", "error", "meta"}.issubset(result.keys()))
        self.assertEqual(result.get("action"), "clinical.extract")

    def test_clinical_extract_always_returns_stable_data_keys(self):
        result = execute_action("clinical.extract", {"transcript": ""})
        self.assertFalse(result.get("ok"))
        data = result.get("data") or {}
        self.assertTrue(EXTRACT_STABLE_KEYS.issubset(data.keys()))

    def test_provider_failure_uses_offline_fallback_with_valid_schema(self):
        original = extractor_module.route_request
        try:
            def _raise(*args, **kwargs):
                raise RuntimeError("provider down")

            extractor_module.route_request = _raise
            transcript = "Doctor: BP 180/110 and chest pain. Patient: sweating and left arm pain."
            result = execute_action("clinical.extract", {"transcript": transcript})
            self.assertTrue(result.get("ok"), msg=str(result))
            data = result.get("data") or {}
            self.assertTrue(EXTRACT_STABLE_KEYS.issubset(data.keys()))
            structured = data.get("structured_data")
            self.assertIsInstance(structured, dict)
            ok, _, errors = validate_clinical_data(structured)
            self.assertTrue(ok, msg=str(errors))
        finally:
            extractor_module.route_request = original

    def test_extract_still_works_when_normalization_fails(self):
        original_normalize = engine_module.normalize_transcript
        original_extract = engine_module.extract_structured
        try:
            def _normalize_fail(*args, **kwargs):
                raise RuntimeError("normalizer down")

            def _extract_ok(transcript: str):
                ok, model, errors = validate_clinical_data(
                    {
                        "encounter_date": None,
                        "encounter_type": "unknown",
                        "patient": {"patient_id": None, "age": None, "gender": "unknown", "occupation": None},
                        "chief_complaint": {"complaint": "headache", "duration": None, "severity": "unknown"},
                        "symptoms": [{"name": "headache", "duration": None, "severity": None, "frequency": None, "notes": None}],
                        "vitals": {
                            "blood_pressure_systolic": None,
                            "blood_pressure_diastolic": None,
                            "heart_rate": None,
                            "temperature": None,
                            "respiratory_rate": None,
                            "oxygen_saturation": None,
                            "weight": None,
                            "height": None,
                            "bmi": None,
                        },
                        "medical_history": {"conditions": [], "surgeries": [], "allergies": [], "medications": [], "family_history": [], "social_history": None},
                        "physical_exam": {"general_appearance": None, "findings": [], "abnormalities": []},
                        "assessment": {"primary_diagnosis": None, "differential_diagnoses": [], "icd10_codes": [], "clinical_impression": None},
                        "treatment_plan": {
                            "medications_prescribed": [],
                            "procedures": [],
                            "referrals": [],
                            "follow_up": None,
                            "patient_instructions": None,
                            "tests_ordered": [],
                        },
                        "clinical_notes": None,
                        "red_flags": [],
                        "confidence_score": 0.4,
                        "missing_data": [],
                    }
                )
                if not ok or model is None:
                    raise RuntimeError(str(errors))
                return model.model_dump()

            engine_module.normalize_transcript = _normalize_fail
            engine_module.extract_structured = _extract_ok
            result = execute_action("clinical.extract", {"transcript": "Doctor: hello\nPatient: headache"})
            self.assertTrue(result.get("ok"), msg=str(result))
            data = result.get("data") or {}
            self.assertTrue(EXTRACT_STABLE_KEYS.issubset(data.keys()))
            self.assertIsInstance(data.get("structured_data"), dict)
        finally:
            engine_module.normalize_transcript = original_normalize
            engine_module.extract_structured = original_extract


if __name__ == "__main__":
    unittest.main()
