import http.server
import socketserver
import json
import os
import sys
import mimetypes
import importlib.util
from pathlib import Path
import uuid

# Ensure we can import from the current directory
# Ensure we can import from the current directory
sys.path.append(os.getcwd())

# Load .env file manually to avoid 'python-dotenv' dependency
env_path = os.path.join(os.getcwd(), ".env")
if os.path.exists(env_path):
    print(f"[Server] Loading environment from {env_path}")
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()
else:
    print("[Server] No .env file found. AI features may be disabled.")

# Import the existing command handler from main.py
try:
    from main import handle_command
    from engine.presenter import wrap_response
except ImportError:
    print("Error: Could not import handle_command from main.py")
    def handle_command(cmd, files=None): return f"Error: Backend connection failed. Command: {cmd}"
    def wrap_response(result, intent="general"):
        return {
            "say_text": str(result),
            "show_text": str(result),
            "evidence": [],
            "files": [],
            "actions": [],
            "meta": {"intent": intent, "verbosity": "quick", "sources": [], "debug": {}},
        }

PORT = 8000
DIRECTORY = "ui"
FILE_REGISTRY = {}
GENERATED_DIR = Path(os.getcwd()) / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve files from the 'ui' directory
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        if self.path.startswith("/ui/"):
            # Alias /ui/* -> static files under DIRECTORY for predictable asset URLs.
            self.path = self.path[len("/ui"):]
        if self.path == "/api/health":
            export_deps = {
                "python_docx": importlib.util.find_spec("docx") is not None,
                "python_pptx": importlib.util.find_spec("pptx") is not None,
                "openpyxl": importlib.util.find_spec("openpyxl") is not None,
            }
            ai = {
                "groq": "ok" if os.environ.get("GROQ_API_KEY") else "fail",
                "gemini": "ok" if os.environ.get("GEMINI_API_KEY") else "fail",
            }
            payload = {"installed_export_deps": export_deps, "ai_providers": ai}
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/download/"):
            file_id = self.path.split("/download/", 1)[1].strip("/")
            path = FILE_REGISTRY.get(file_id)
            if not path or not Path(path).exists():
                self.send_error(404, "File not found")
                return
            file_path = Path(path)
            ctype, _ = mimetypes.guess_type(str(file_path))
            ctype = ctype or "application/octet-stream"
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/command":
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                command = data.get("command", "")
                files = data.get("files", [])
                
                print(f"[Server] Received command: {command} | Files: {len(files)}")
                
                # Call the actual engine logic
                result = handle_command(command, files)
                response = wrap_response(result)
                normalized_files = []
                for fmeta in response.get("files", []) or []:
                    if not isinstance(fmeta, dict):
                        continue
                    file_id = fmeta.get("id") or str(uuid.uuid4())[:12]
                    file_path = fmeta.get("path")
                    if file_path and Path(file_path).exists():
                        FILE_REGISTRY[file_id] = file_path
                    normalized_files.append(
                        {
                            "id": file_id,
                            "type": fmeta.get("type", ""),
                            "name": fmeta.get("name", ""),
                            "url": f"/download/{file_id}",
                            "size": int(fmeta.get("size", 0) or 0),
                        }
                    )
                response["files"] = normalized_files
                intent = ((response.get("meta") or {}).get("intent")) if isinstance(response, dict) else None
                action = response.get("action") if isinstance(response, dict) else None
                preview = (response.get("show_text", "") or "").replace("\n", " ")
                preview = preview[:140] + ("..." if len(preview) > 140 else "")
                print(f"[Server] Intent: {intent or 'unknown'} | Action: {action or 'n/a'}")
                print(f"[Server] Reply: {preview}")
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                print(f"[Server] Error: {e}")
                safe = wrap_response(
                    {
                        "say_text": "I hit an internal error while processing that request.",
                        "show_text": "I hit an internal error while processing that request. Please retry.",
                        "evidence": [],
                        "files": [],
                        "actions": [],
                        "meta": {"intent": "error", "verbosity": "quick", "sources": [], "debug": {}},
                    }
                )
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(safe).encode('utf-8'))
        else:
            self.send_error(404)

print(f"Starting Jarvis Web Server at http://localhost:{PORT}")
print("Press Ctrl+C to stop.")

# Allow address reuse to prevent "Address already in use" errors on restart
socketserver.TCPServer.allow_reuse_address = True

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.shutdown()
