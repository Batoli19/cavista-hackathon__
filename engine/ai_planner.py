"""
Deprecated for clinical demo scope.
This module is kept only for backward compatibility and is not used by the
clinical session MVP flow.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL_CANDIDATES = [GEMINI_MODEL, "gemini-1.5-flash", "gemini-1.5-flash-8b"]

CACHE_TTL_SECONDS = 300
_PLAN_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}


def _cache_get(key: str) -> List[Dict[str, Any]] | None:
    item = _PLAN_CACHE.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at < time.time():
        _PLAN_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: List[Dict[str, Any]]) -> None:
    _PLAN_CACHE[key] = (time.time() + CACHE_TTL_SECONDS, value)


def _with_retry(call_fn):
    delay = 0.8
    last_err = None
    for _ in range(3):
        try:
            return call_fn()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 403:
                raise
            if e.code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(delay)
            delay *= 2
    if last_err:
        raise last_err


def _local_fallback_plan(project_name: str, description: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "t1",
            "name": "Define scope",
            "description": f"Define project scope for {project_name}. {description}",
            "duration_days": 1,
            "depends_on": [],
            "priority": "high",
            "role": "general",
        },
        {
            "id": "t2",
            "name": "Collect requirements",
            "description": "Gather requirements and constraints from stakeholders.",
            "duration_days": 2,
            "depends_on": ["t1"],
            "priority": "high",
            "role": "general",
        },
        {
            "id": "t3",
            "name": "Build implementation plan",
            "description": "Create phased implementation plan with owners and timelines.",
            "duration_days": 2,
            "depends_on": ["t2"],
            "priority": "high",
            "role": "general",
        },
        {
            "id": "t4",
            "name": "Execute pilot",
            "description": "Run a pilot to validate assumptions.",
            "duration_days": 3,
            "depends_on": ["t3"],
            "priority": "medium",
            "role": "general",
        },
        {
            "id": "t5",
            "name": "Review and scale",
            "description": "Review pilot outcomes and plan full rollout.",
            "duration_days": 2,
            "depends_on": ["t4"],
            "priority": "medium",
            "role": "general",
        },
    ]


def generate_plan_ai(project_name: str, description: str, team_size: int = 1) -> List[Dict[str, Any]]:
    prompt = f"""
Act as a senior project manager.
Create a detailed work breakdown structure (WBS) for "{project_name}".
Description: {description}
Team size: {team_size}

Return a JSON array of tasks. Each task must include:
- id (t1, t2, ...)
- name
- description
- duration_days (1-5)
- depends_on (list of task ids)
- priority (low|medium|high)
- role

Return ONLY valid JSON.
"""
    cache_key = f"{project_name}|{description}|{team_size}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    if GROQ_API_KEY:
        try:
            tasks = _generate_with_groq(prompt)
            _cache_set(cache_key, tasks)
            return tasks
        except Exception:
            pass

    if GEMINI_API_KEY:
        try:
            tasks = _generate_with_gemini(prompt)
            _cache_set(cache_key, tasks)
            return tasks
        except Exception:
            pass

    tasks = _local_fallback_plan(project_name, description)
    _cache_set(cache_key, tasks)
    return tasks


def _generate_with_groq(prompt: str) -> List[Dict[str, Any]]:
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "You are a project planning expert. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 2000,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {GROQ_API_KEY}"},
    )

    def _call():
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body)
            return parsed["choices"][0]["message"]["content"]

    content = _with_retry(_call)
    return _parse_tasks(content)


def _generate_with_gemini(prompt: str) -> List[Dict[str, Any]]:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5, "responseMimeType": "application/json"},
    }
    data_json = json.dumps(payload).encode("utf-8")

    last_error: Exception | None = None
    for model in GEMINI_MODEL_CANDIDATES:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        req = urllib.request.Request(url, data=data_json, headers={"Content-Type": "application/json"})
        try:
            def _call():
                with urllib.request.urlopen(req, timeout=20) as response:
                    body = response.read().decode("utf-8")
                    return json.loads(body)

            parsed = _with_retry(_call)
            content = parsed["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_tasks(content)
        except Exception as e:
            last_error = e
            continue
    raise last_error or RuntimeError("Gemini unavailable")


def _parse_tasks(content: str) -> List[Dict[str, Any]]:
    cleaned = (content or "").replace("```json", "").replace("```", "").strip()
    tasks = json.loads(cleaned)
    if isinstance(tasks, dict) and "tasks" in tasks:
        tasks = tasks["tasks"]
    if not isinstance(tasks, list):
        raise ValueError("Task output is not a list.")
    return tasks
