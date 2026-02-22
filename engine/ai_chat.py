import json
import os
import urllib.request
import urllib.error
import time
import random
from typing import List, Dict, Any

import base64
import io
import zipfile
import xml.etree.ElementTree as ET

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION — Groq first, Gemini only for vision
# ══════════════════════════════════════════════════════════════════════════════

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")


def _normalize_gemini_model_id(model: str) -> str:
    """
    Ensures Gemini model ID does not contain 'models/' prefix.
    """
    m = (model or "").strip()
    if m.startswith("models/"):
        m = m.split("models/", 1)[1]
    return m


# Models
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
CACHE_TTL_SECONDS = 300
_TEXT_CACHE: Dict[str, tuple[float, str]] = {}
_GEMINI_MODEL_CANDIDATES = [GEMINI_MODEL, "gemini-1.5-flash", "gemini-1.5-flash-8b"]
_GEMINI_MODEL_CANDIDATES = [
    _normalize_gemini_model_id(m)
    for m in _GEMINI_MODEL_CANDIDATES
    if m
]

STYLE_RULES = (
    "You are a concise assistant.\n"
    "Style rules:\n"
    "- No roleplay.\n"
    "- No unexplained acronyms.\n"
    "- Do not say phrases like 'pleasure to meet you'.\n"
    "- Default format: 1 sentence, then up to 3 bullets, then either 1 question OR 2-3 choices.\n"
    "- Ask clarifying questions only if required, and at most 2.\n"
    "- Keep tone natural and direct.\n"
)


def _cache_get(key: str) -> str | None:
    hit = _TEXT_CACHE.get(key)
    if not hit:
        return None
    exp, value = hit
    if exp < time.time():
        _TEXT_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: str) -> None:
    _TEXT_CACHE[key] = (time.time() + CACHE_TTL_SECONDS, value)


def _local_fallback_response(message: str) -> str:
    preview = (message or "").strip()
    if len(preview) > 120:
        preview = preview[:120] + "..."
    return (
        "I could not reach the main models right now.\n"
        f"- Request captured: {preview or 'No text provided'}\n"
        "- Try again in a moment, or ask for a shorter response.\n"
        "Would you like a quick outline instead?"
    )


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


def _list_gemini_models() -> list[str]:
    """
    Fetch available Gemini models that support generateContent.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    discovered = []
    for item in data.get("models", []):
        name = item.get("name", "")
        supported = item.get("supportedGenerationMethods", [])
        if name.startswith("models/") and "generateContent" in supported:
            discovered.append(name.split("models/", 1)[1])

    return discovered


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER: Check if files contain images
# ══════════════════════════════════════════════════════════════════════════════

def _has_images(files: List[Dict[str, Any]]) -> bool:
    """Check if any file is an image."""
    if not files:
        return False
    for file in files:
        mime = file.get("type", "").lower()
        name = file.get("name", "").lower()
        if mime.startswith("image/") or name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
            return True
    return False


def _extract_text_from_file(base64_data: str, mime_type: str, filename: str) -> str:
    """
    Extracts text from base64 encoded file data.
    Supports: .txt, .docx, code files.
    """
    try:
        file_bytes = base64.b64decode(base64_data)
        
        # 1. DOCX Handling
        if "wordprocessingml.document" in mime_type or filename.endswith(".docx"):
            try:
                with io.BytesIO(file_bytes) as f:
                    with zipfile.ZipFile(f) as z:
                        xml_content = z.read("word/document.xml")
                        tree = ET.fromstring(xml_content)
                        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                        text_parts = []
                        for node in tree.iter():
                            if node.tag == f"{{{ns['w']}}}t":
                                if node.text:
                                    text_parts.append(node.text)
                            elif node.tag == f"{{{ns['w']}}}p":
                                text_parts.append("\n")
                        return "".join(text_parts).strip()
            except Exception as e:
                print(f"[Text Extraction] Failed to parse DOCX: {e}")
                return None

        # 2. Plain Text / Code
        try:
            return file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            print(f"[Text Extraction] Could not decode file as UTF-8: {mime_type}")
            return None

    except Exception as e:
        print(f"[Text Extraction] Error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT — Smart routing
# ══════════════════════════════════════════════════════════════════════════════

def chat_with_ai(message: str, files: List[Dict[str, Any]] = None) -> str:
    """
    Smart AI router:
    - Has images? → Gemini vision (ONLY path that uses Gemini)
    - Text only? → Groq (FAST, unlimited, DEFAULT)
    
    This is the NEW optimized version — Groq first, not Gemini.
    """
    if not message and not files:
        return "I'm listening..."

    files = files or []
    cache_key = f"text::{message.strip()}" if message and not files else ""
    if cache_key:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    # ── VISION PATH: Images detected → use Gemini ────────────────────────
    if _has_images(files):
        print("[AI Chat] Images detected -> routing to Gemini vision")
        return _chat_with_gemini_vision(message, files)

    # ── TEXT PATH: Default to Groq (FAST) ────────────────────────────────
    print("[AI Chat] Text only -> routing to Groq (fast)")
    
    # Extract text from non-image files and append to message
    if files:
        text_content = []
        for file in files:
            mime = file.get("type", "")
            name = file.get("name", "unknown")
            b64_data = file.get("content", "")
            
            extracted = _extract_text_from_file(b64_data, mime, name)
            if extracted:
                text_content.append(f"\n--- File: {name} ---\n{extracted}\n--- End of {name} ---\n")
        
        if text_content:
            message += "\n\n" + "".join(text_content)
    
    # Try Groq first
    if GROQ_API_KEY:
        try:
            out = _chat_with_groq(message)
            if cache_key:
                _cache_set(cache_key, out)
            return out
        except Exception as e:
            print(f"[AI Chat] Groq failed: {e}")
            # Fallback to Gemini if Groq fails
            if GEMINI_API_KEY:
                print("[AI Chat] Falling back to Gemini (text only)")
                try:
                    out = _chat_with_gemini_text(message)
                    if cache_key:
                        _cache_set(cache_key, out)
                    return out
                except Exception:
                    pass
            return _local_fallback_response(message)
    
    # No Groq key? Try Gemini
    if GEMINI_API_KEY:
        print("[AI Chat] No Groq key, using Gemini (text only)")
        try:
            out = _chat_with_gemini_text(message)
            if cache_key:
                _cache_set(cache_key, out)
            return out
        except Exception:
            return _local_fallback_response(message)
    
    return _local_fallback_response(message)


# ══════════════════════════════════════════════════════════════════════════════
#  GROQ — Fast, unlimited, text-only (DEFAULT)
# ══════════════════════════════════════════════════════════════════════════════

def _chat_with_groq(message: str, temperature: float = 0.7) -> str:
    """
    Groq API — fast, unlimited free tier, text only.
    This is the DEFAULT path for all text queries.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": STYLE_RULES},
            {"role": "user", "content": message}
        ],
        "temperature": float(temperature),
        "max_tokens": 1024
    }
    
    data = json.dumps(payload).encode("utf-8")
    
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "JARVIS/1.0"
        }
    )
    
    def _call():
        with urllib.request.urlopen(req, timeout=15) as response:
            resp_body = response.read().decode("utf-8")
            resp_data = json.loads(resp_body)
            return resp_data["choices"][0]["message"]["content"].strip()

    try:
        return _with_retry(_call)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        raise Exception(f"Groq HTTP {e.code}: {error_body}")
    except Exception as e:
        raise Exception(f"Groq error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  GEMINI — Only for vision (images) or fallback
# ══════════════════════════════════════════════════════════════════════════════

def _chat_with_gemini_vision(message: str, files: List[Dict[str, Any]]) -> str:
    """
    Gemini vision — ONLY for image analysis.
    Single attempt, no retry loops (to avoid rate limit cascades).
    """
    if not GEMINI_API_KEY:
        return "Vision unavailable (no GEMINI_API_KEY). Please add images via upload."

    try:
        parts = []
        if message:
            parts.append({"text": f"{STYLE_RULES}\nUser request:\n{message}"})

        # Add files
        for file in files:
            mime_type = file.get("type", "application/octet-stream")
            base64_data = file.get("content", "")
            name = file.get("name", "unknown")
            
            # Images, audio, PDF → inline
            if mime_type.startswith("image/") or mime_type.startswith("audio/") or mime_type == "application/pdf":
                parts.append({
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64_data
                    }
                })
            else:
                # Extract text from other files
                extracted = _extract_text_from_file(base64_data, mime_type, name)
                if extracted:
                    parts.append({"text": f"\n[File: {name}]\n{extracted}\n[End of file]\n"})

        payload = {"contents": [{"parts": parts}]}
        data_json = json.dumps(payload).encode("utf-8")

        last_error = None
        for model in _GEMINI_MODEL_CANDIDATES:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            req = urllib.request.Request(url, data=data_json, headers={"Content-Type": "application/json"})
            try:
                def _call():
                    with urllib.request.urlopen(req, timeout=20) as response:
                        resp_body = response.read().decode("utf-8")
                        return json.loads(resp_body)
                resp_data = _with_retry(_call)
                try:
                    return resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except (KeyError, IndexError):
                    return "Vision request completed but returned no text."
            except Exception as e:
                last_error = e
                continue
        raise last_error if last_error else Exception("Gemini vision unavailable")

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        print(f"[Gemini Vision] HTTP {e.code}: {error_body}")
        
        # If rate limited, try Groq as text fallback
        if e.code == 429 and GROQ_API_KEY:
            print("[Gemini Vision] Rate limited. Falling back to Groq (text only, no vision).")
            fallback_msg = f"{message}\n\n[Note: Images were attached but Gemini is rate-limited. Answering text only.]"
            try:
                return _chat_with_groq(fallback_msg)
            except:
                pass
        
        return f"Vision error: HTTP {e.code} - Gemini overloaded. Try again in a minute."
    
    except Exception as e:
        print(f"[Gemini Vision] Error: {e}")
        return f"Vision error: {e}"


def _chat_with_gemini_text(message: str, temperature: float = 0.7) -> str:
    """
    Gemini text-only mode (fallback when Groq unavailable).
    Single attempt, no retries.
    """
    if not GEMINI_API_KEY:
        return "AI unavailable (no API keys configured)."

    try:
        payload = {
            "contents": [{"parts": [{"text": f"{STYLE_RULES}\nUser request:\n{message}"}]}],
            "generationConfig": {"temperature": float(temperature)},
        }
        data_json = json.dumps(payload).encode("utf-8")

        last_error = None
        for model in _GEMINI_MODEL_CANDIDATES:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            req = urllib.request.Request(url, data=data_json, headers={"Content-Type": "application/json"})
            try:
                def _call():
                    with urllib.request.urlopen(req, timeout=15) as response:
                        resp_body = response.read().decode("utf-8")
                        return json.loads(resp_body)
                resp_data = _with_retry(_call)
                try:
                    return resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except (KeyError, IndexError):
                    return "Gemini returned no response."
            except Exception as e:
                last_error = e
                continue
        # If 404 occurred, try auto-discovered models
        if isinstance(last_error, urllib.error.HTTPError) and last_error.code == 404:
            try:
                discovered = _list_gemini_models()
                for model in discovered[:5]:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
                    req = urllib.request.Request(url, data=data_json, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=15) as response:
                        resp_body = response.read().decode("utf-8")
                        resp_data = json.loads(resp_body)
                        return resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception:
                pass
        raise last_error if last_error else Exception("Gemini unavailable")

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        print(f"[Gemini Text] HTTP {e.code}: {error_body}")
        return f"Gemini error: {e.code} - Rate limited or overloaded."
    
    except Exception as e:
        print(f"[Gemini Text] Error: {e}")
        return f"Gemini error: {e}"
