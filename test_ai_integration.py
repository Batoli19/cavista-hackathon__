import os
import sys
import unittest

# Ensure we can import from the current directory
sys.path.append(os.getcwd())

from engine.engine import execute_action
import engine.engine as engine_module
from engine.clinical.schema import validate_clinical_data
import engine.clinical.extractor as extractor_module
from main import handle_command


STABLE_CLINICAL_DATA_KEYS = {
    "session",
    "session_id",
    "transcript",
    "structured_data",
    "red_flags",
    "missing_data",
}

STABLE_INSIGHTS_DATA_KEYS = {
    "session_id",
    "structured_data",
    "diagnosis_support",
    "actionable_insights",
    "analytics",
}


class TestClinicalMvp1(unittest.TestCase):
    def test_transcript_like_input_routes_to_clinical_extract(self):
        transcript = "Doctor: What brings you in?\nPatient: Chest pain for two hours."
        result = handle_command(transcript)
        self.assertEqual(result.get("meta", {}).get("intent"), "clinical_extract")

    def test_clinical_extract_contract_and_stable_data_keys(self):
        result = execute_action("clinical.extract", {"transcript": "Doctor: hello\nPatient: headache"})
        self.assertTrue({"action", "ok", "data", "error", "meta"}.issubset(result.keys()))
        self.assertEqual(result.get("action"), "clinical.extract")
        self.assertIsInstance(result.get("data"), dict)
        self.assertTrue(STABLE_CLINICAL_DATA_KEYS.issubset(result.get("data", {}).keys()))

    def test_success_path_structured_data_validates(self):
        original = extractor_module.route_request
        try:
            extractor_module.route_request = lambda prompt, task_type="reasoning", context=None, files=None: (
                '{"encounter_date": null, "encounter_type": "outpatient", "patient": {"patient_id": null, "age": 45, "gender": "male", "occupation": null}, '
                '"chief_complaint": {"complaint": "chest pain", "duration": "2 hours", "severity": "moderate"}, '
                '"symptoms": [{"name": "chest pain", "duration": "2 hours", "severity": "moderate", "frequency": null, "notes": null}], '
                '"vitals": {"blood_pressure_systolic": 140, "blood_pressure_diastolic": 90, "heart_rate": 88, "temperature": null, "respiratory_rate": null, "oxygen_saturation": null, "weight": null, "height": null, "bmi": null}, '
                '"medical_history": {"conditions": [], "surgeries": [], "allergies": [], "medications": [], "family_history": [], "social_history": null}, '
                '"physical_exam": {"general_appearance": null, "findings": [], "abnormalities": []}, '
                '"assessment": {"primary_diagnosis": null, "differential_diagnoses": [], "icd10_codes": [], "clinical_impression": null}, '
                '"treatment_plan": {"medications_prescribed": [], "procedures": [], "referrals": [], "follow_up": null, "patient_instructions": null, "tests_ordered": []}, '
                '"clinical_notes": null, "red_flags": [], "confidence_score": 0.8, "missing_data": []}'
            )
            result = execute_action("clinical.extract", {"transcript": "Doctor: ...\nPatient: ..."})
            self.assertTrue(result.get("ok"))
            data = result.get("data", {})
            structured = data.get("structured_data")
            self.assertIsInstance(structured, dict)
            ok, _, errors = validate_clinical_data(structured)
            self.assertTrue(ok, msg=str(errors))
        finally:
            extractor_module.route_request = original

    def test_fallback_path_when_provider_unavailable(self):
        original = extractor_module.route_request
        try:
            def _raise(*args, **kwargs):
                raise RuntimeError("provider down")
            extractor_module.route_request = _raise
            transcript = "Doctor: BP 180/110 and chest pain. Patient: sweating and left arm pain."
            result = execute_action("clinical.extract", {"transcript": transcript})
            self.assertTrue(result.get("ok"), msg=str(result))
            data = result.get("data", {})
            self.assertTrue(STABLE_CLINICAL_DATA_KEYS.issubset(data.keys()))
            structured = data.get("structured_data")
            self.assertIsInstance(structured, dict)
            ok, _, errors = validate_clinical_data(structured)
            self.assertTrue(ok, msg=str(errors))
        finally:
            extractor_module.route_request = original

    def test_patient_doc_after_extract_by_session_id(self):
        transcript = (
            "Doctor: What brings you in today?\n"
            "Patient: I have chest pain and shortness of breath.\n"
            "Doctor: BP is 150/95 and heart rate 102.\n"
            "Doctor: We will order ECG and troponin and follow up tomorrow."
        )
        extract_result = execute_action("clinical.extract", {"transcript": transcript})
        self.assertTrue(extract_result.get("ok"), msg=str(extract_result))
        session_id = (extract_result.get("data") or {}).get("session_id")
        self.assertTrue(session_id)

        doc_result = execute_action("clinical.patient_doc", {"session_id": session_id})
        self.assertTrue({"action", "ok", "data", "error", "meta"}.issubset(doc_result.keys()))
        self.assertEqual(doc_result.get("action"), "clinical.patient_doc")
        self.assertTrue(doc_result.get("ok"), msg=str(doc_result))

        data = doc_result.get("data") or {}
        self.assertIn("doc_markdown", data)
        markdown = str(data.get("doc_markdown") or "")
        self.assertIn("When to seek urgent care NOW", markdown)

    def test_clinical_insights_from_transcript_returns_graph_ready_lists(self):
        transcript = (
            "Doctor: What brings you in today?\n"
            "Patient: I have chest pain and shortness of breath.\n"
            "Doctor: BP is 150/95 and heart rate 102.\n"
            "Doctor: We will order ECG and troponin and follow up tomorrow."
        )
        result = execute_action("clinical.insights", {"transcript": transcript})
        self.assertTrue({"action", "ok", "data", "error", "meta"}.issubset(result.keys()))
        self.assertEqual(result.get("action"), "clinical.insights")
        self.assertTrue(result.get("ok"), msg=str(result))
        data = result.get("data") or {}
        self.assertTrue(STABLE_INSIGHTS_DATA_KEYS.issubset(data.keys()))
        diagnosis = data.get("diagnosis_support") or {}
        self.assertIn(diagnosis.get("risk_tier"), {"low", "medium", "high"})
        analytics = data.get("analytics") or {}
        self.assertIsInstance(analytics.get("summary_cards"), list)
        self.assertIsInstance(analytics.get("vitals"), list)
        self.assertIsInstance(analytics.get("risk_scores"), list)
        soap = data.get("soap_note") or {}
        self.assertTrue({"subjective", "objective", "assessment", "plan"}.issubset(soap.keys()))

    def test_clinical_insights_failure_keeps_stable_keys(self):
        original = engine_module.extract_structured
        try:
            def _raise(*args, **kwargs):
                raise RuntimeError("extract fail")
            engine_module.extract_structured = _raise
            result = execute_action("clinical.insights", {"transcript": "Doctor: hi\nPatient: headache for 1 day"})
            self.assertFalse(result.get("ok"))
            self.assertTrue({"action", "ok", "data", "error", "meta"}.issubset(result.keys()))
            self.assertEqual(result.get("action"), "clinical.insights")
            data = result.get("data") or {}
            self.assertTrue(STABLE_INSIGHTS_DATA_KEYS.issubset(data.keys()))
            diagnosis = data.get("diagnosis_support") or {}
            self.assertIn(diagnosis.get("risk_tier"), {"low", "medium", "high"})
            analytics = data.get("analytics") or {}
            self.assertIn("summary_cards", analytics)
            self.assertIn("vitals", analytics)
            self.assertIn("risk_scores", analytics)
        finally:
            engine_module.extract_structured = original


if __name__ == "__main__":
    unittest.main()
