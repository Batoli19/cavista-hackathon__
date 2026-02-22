Healthcare documentation is broken.

Clinicians spend more time typing than treating. In many African healthcare systems — especially in Botswana — language barriers, documentation overload, and fragmented systems reduce care quality.

We asked:

What if a clinician could just speak — and the system handled everything else?

This project is our answer.

🚀 What It Does

Our platform is a Voice-First Clinical Assistant that:

🎙️ Converts clinician–patient conversations into structured medical data

🧠 Extracts symptoms, vitals, diagnosis clues, and medications

📊 Generates actionable insights in real time

🗂️ Automatically structures documentation

🌐 Supports Setswana for localized care delivery

📈 Provides dashboards for clinical intelligence

It transforms natural speech into:

{
  "patient_name": "Mpho",
  "symptoms": ["headache", "fever"],
  "duration": "3 days",
  "possible_diagnosis": "malaria",
  "risk_level": "medium",
  "recommended_action": "lab test"
}

No typing. No manual structuring. Just intelligent care.

🧠 Core Features
1️⃣ Voice → Structured Clinical Data

Real-time speech-to-text

AI-powered medical entity extraction

Auto SOAP note generation

2️⃣ Clinical Insight Engine

Risk scoring

Symptom clustering

Early diagnosis suggestions

Pattern detection

3️⃣ Smart Dashboard

Patient summaries

Trends & alerts

Predictive flags

Actionable recommendations

4️⃣ Setswana-Ready System 🇧🇼

Designed specifically for Botswana healthcare workflows.

We are building multilingual NLP pipelines to:

Detect Setswana medical phrases

Normalize into structured English medical fields

Preserve local patient communication authenticity

🏗️ How We Built It
🖥️ Backend

Python (Flask API server)

AI routing engine

Real-time processing pipeline

SSE (Server-Sent Events) for live updates

🧠 AI Layer

LLM-powered medical parsing

Custom extraction prompts

Confidence scoring logic

Insight generation engine

🌐 Frontend

Modern dashboard UI

Live data streaming

Responsive layout

Premium medical interface design

🔊 Voice Integration

Speech-to-text processing

Real-time transcription

Structured output pipeline

🏥 System Architecture
Voice Input
    ↓
Speech-to-Text
    ↓
AI Extraction Engine
    ↓
Structured Medical Data
    ↓
Insight & Risk Engine
    ↓
Live Clinical Dashboard
