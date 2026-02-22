import json
from engine.engine import execute_action

transcript = """Doctor: What brings you in today?
Patient: I have chest pain for 2 hours radiating to my left arm.
Doctor: Any sweating or nausea?
Patient: Yes sweating and nausea.
Doctor: Vitals: BP 160/100, HR 102, SpO2 95%.
Doctor: Plan ECG and troponin. Give aspirin and refer urgently to ER.
"""

result = execute_action("clinical.extract", {"transcript": transcript})

print("\n=== ACTION CONTRACT ===")
print(json.dumps({k: result.get(k) for k in ["action", "ok", "error", "meta"]}, indent=2))

data = result.get("data") or {}
print("\n=== STRUCTURED_DATA (FULL) ===")
print(json.dumps(data.get("structured_data"), indent=2))

print("\n=== RED FLAGS ===")
print(json.dumps(data.get("red_flags"), indent=2))

print("\n=== MISSING DATA ===")
print(json.dumps(data.get("missing_data"), indent=2))