from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, ValidationError


class PatientInfo(BaseModel):
    patient_id: str | None = None
    age: int | None = None
    gender: Literal["male", "female", "other", "unknown"] = "unknown"
    occupation: str | None = None


class ChiefComplaint(BaseModel):
    complaint: str
    duration: str | None = None
    severity: Literal["mild", "moderate", "severe", "unknown"] = "unknown"


class Symptom(BaseModel):
    name: str
    duration: str | None = None
    severity: Literal["mild", "moderate", "severe"] | None = None
    frequency: str | None = None
    notes: str | None = None


class VitalSign(BaseModel):
    blood_pressure_systolic: int | None = None
    blood_pressure_diastolic: int | None = None
    heart_rate: int | None = None
    temperature: float | None = None
    respiratory_rate: int | None = None
    oxygen_saturation: int | None = None
    weight: float | None = None
    height: float | None = None
    bmi: float | None = None


class MedicalHistory(BaseModel):
    conditions: List[str] = Field(default_factory=list)
    surgeries: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    medications: List[str] = Field(default_factory=list)
    family_history: List[str] = Field(default_factory=list)
    social_history: str | None = None


class PhysicalExam(BaseModel):
    general_appearance: str | None = None
    findings: List[str] = Field(default_factory=list)
    abnormalities: List[str] = Field(default_factory=list)


class Assessment(BaseModel):
    primary_diagnosis: str | None = None
    differential_diagnoses: List[str] = Field(default_factory=list)
    icd10_codes: List[str] = Field(default_factory=list)
    clinical_impression: str | None = None


class TreatmentPlan(BaseModel):
    medications_prescribed: List[str] = Field(default_factory=list)
    procedures: List[str] = Field(default_factory=list)
    referrals: List[str] = Field(default_factory=list)
    follow_up: str | None = None
    patient_instructions: str | None = None
    tests_ordered: List[str] = Field(default_factory=list)


class ClinicalEncounter(BaseModel):
    encounter_date: str | None = None
    encounter_type: Literal["inpatient", "outpatient", "emergency", "telehealth", "unknown"] = "unknown"
    patient: PatientInfo = Field(default_factory=PatientInfo)
    chief_complaint: ChiefComplaint | None = None
    symptoms: List[Symptom] = Field(default_factory=list)
    vitals: VitalSign = Field(default_factory=VitalSign)
    medical_history: MedicalHistory = Field(default_factory=MedicalHistory)
    physical_exam: PhysicalExam = Field(default_factory=PhysicalExam)
    assessment: Assessment = Field(default_factory=Assessment)
    treatment_plan: TreatmentPlan = Field(default_factory=TreatmentPlan)
    clinical_notes: str | None = None
    red_flags: List[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    missing_data: List[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"


def model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def validate_clinical_data(data: dict) -> tuple[bool, ClinicalEncounter | None, List[str]]:
    try:
        return True, ClinicalEncounter(**data), []
    except ValidationError as exc:
        issues: List[str] = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", []))
            issues.append(f"{loc}: {err.get('msg', 'invalid value')}")
        return False, None, issues
    except Exception as exc:
        return False, None, [str(exc)]
