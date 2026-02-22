"""
Deprecated for clinical demo scope.
Research-based planning is not part of the clinical session MVP.
"""

from __future__ import annotations

from typing import Any, Dict


def create_project_plan_from_web_request(user_text: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "message": "Research planning is deprecated in the clinical demo.",
        "input": user_text,
    }
