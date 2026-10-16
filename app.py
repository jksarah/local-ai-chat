import json
import logging
import io
import os

import requests
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # max request size (uploads/images)
CORS(app)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("localmind")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "llama3:latest")
KEEP_ALIVE = os.environ.get("KEEP_ALIVE", "30m")
# (connect timeout, read timeout between chunks) in seconds
REQUEST_TIMEOUT = (5, 300)
# Context window; larger so attached documents are not silently cut off by Ollama
NUM_CTX = int(os.environ.get("NUM_CTX", "8192"))
# Max characters of extracted text kept per attached file
MAX_FILE_CHARS = int(os.environ.get("MAX_FILE_CHARS", "20000"))
MAX_PDF_PAGES = 100

SYSTEM_MESSAGE = {
    "role": "system",
    "content": """
You are LocalMind, a helpful local AI assistant.

Answer questions directly and clearly.
You can help with programming, debugging, software development,
technical explanations, writing, and general knowledge.

For technical questions:
- Give practical solutions.
- Provide code examples when useful.
- Explain errors clearly.
- Do not unnecessarily refuse technical questions.
- If you are unsure, say so instead of inventing information.

Use clean Markdown formatting.
""",
}

VALID_ROLES = {"user", "assistant"}


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/models")
def models():
    """List models installed in Ollama."""
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=5)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException as e:
        log.warning("Could not list models: %s", e)
        return jsonify(error="Cannot reach Ollama", models=[], default=DEFAULT_MODEL), 503
    return jsonify(models=names, default=DEFAULT_MODEL)


def _clip(text):
    if len(text) > MAX_FILE_CHARS:
        return text[:MAX_FILE_CHARS] + "\n[...truncated...]", True
    return text, False


@app.route("/api/extract", methods=["POST"])
def extract():
    """Extract text from an uploaded PDF or plain-text file."""
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify(error="No file uploaded"), 400
    name = os.path.basename(f.filename)
    data = f.read()
    if name.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages[:MAX_PDF_PAGES]:
                parts.append(page.extract_text() or "")
            text = "\n\n".join(parts).strip()
        except Exception as e:  # corrupt/encrypted PDFs raise many error types
            log.warning("PDF extract failed: %s", e)
            return jsonify(error="Could not read this PDF (corrupt or encrypted?)"), 422
        if not text:
            return jsonify(error="No text found in this PDF (scanned PDFs are not supported)"), 422
    else:
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            return jsonify(error="Unsupported file type"), 415
    text, truncated = _clip(text)
    return jsonify(name=name, text=text, truncated=truncated)


def _to_ollama_message(m):
    """Convert a UI message (text + optional files/images) to an Ollama message."""
    content = m["content"]
    files = m.get("files") or []
    if files:
        docs = "".join(
            f"[Attached file: {f['name']}]\n{f['text']}\n[End of file]\n\n" for f in files
        )
        content = docs + content
    out = {"role": m["role"], "content": content}
    images = m.get("images") or []
    if images:
        # strip "data:image/...;base64," prefix
        out["images"] = [i.split(",", 1)[-1] for i in images]
    return out


def _valid_attachments(m):
    files, images = m.get("files"), m.get("images")
    if files is not None:
        if not isinstance(files, list) or not all(
            isinstance(f, dict) and isinstance(f.get("name"), str) and isinstance(f.get("text"), str)
            for f in files
        ):
            return False
    if images is not None:
        if not isinstance(images, list) or not all(isinstance(i, str) for i in images):
            return False
    return True


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Request body must be JSON"), 400

    messages = data.get("messages", [])
    model = data.get("model") or DEFAULT_MODEL

    if not isinstance(messages, list) or not messages:
        return jsonify(error="'messages' must be a non-empty list"), 400
    for m in messages:
        if (
            not isinstance(m, dict)
            or m.get("role") not in VALID_ROLES
            or not isinstance(m.get("content"), str)
        ):
            return jsonify(error="Each message needs a valid 'role' and string 'content'"), 400
        if not _valid_attachments(m):
            return jsonify(error="Invalid 'files' or 'images' in message"), 400

    log.info("Chat request: model=%s, messages=%d", model, len(messages))
    payload = {
        "model": model,
        "messages": [SYSTEM_MESSAGE] + [_to_ollama_message(m) for m in messages],
        "options": {"num_ctx": NUM_CTX},
        "stream": True,
        "keep_alive": KEEP_ALIVE,
    }

    # Open the upstream connection before streaming so failures become real HTTP errors.
    try:
        upstream = requests.post(
            OLLAMA_CHAT_URL, json=payload, stream=True, timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as e:
        log.error("Ollama unreachable: %s", e)
        return jsonify(error="Cannot reach Ollama. Is it running?"), 502

    if upstream.status_code != 200:
        try:
            detail = upstream.json().get("error", upstream.text)
        except ValueError:
            detail = upstream.text
        upstream.close()
        return jsonify(error=f"Ollama error: {detail}"), 502

    def generate():
        try:
            for line in upstream.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line.decode("utf-8"))
                if "error" in chunk:
                    yield f"\n\n[Error: {chunk['error']}]"
                    return
                yield chunk.get("message", {}).get("content", "")
                if chunk.get("done"):
                    return
        except (requests.RequestException, ValueError) as e:
            log.error("Stream interrupted: %s", e)
            yield "\n\n[Error: response stream interrupted]"
        finally:
            upstream.close()

    return Response(generate(), content_type="text/plain; charset=utf-8")


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
        threaded=True,
    )
