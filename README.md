# local-ai-chat

A small Flask web app that provides a chat interface (LocalMind) for local LLMs served by [Ollama](https://ollama.com).

## Features

- Fully offline: Markdown libraries are bundled in `static/vendor/` (no CDN)
- Syntax-highlighted code blocks with a Copy button
- Browser chat UI (`templates/index.html`) with Markdown rendering (sanitized with DOMPurify)
- Streams responses token-by-token from Ollama, with a Stop button
- Model dropdown is filled from the models installed in Ollama; your choice is remembered
- Chat history stored in the browser (`localStorage`)
- Clear error messages when Ollama is down or returns an error
- Built-in system prompt for a helpful programming/general assistant
- Models kept loaded for 30 minutes (`keep_alive`)

## Requirements

- Python 3.8+
- [Ollama](https://ollama.com) running locally on `localhost:11434`
- At least one pulled model, e.g. `ollama pull llama3`

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000.

## API

`GET /api/models` – returns `{ "models": ["llama3:latest", ...], "default": "llama3:latest" }`.

`POST /api/chat`

```json
{
  "model": "llama3:latest",
  "messages": [{ "role": "user", "content": "Hello" }]
}
```

Returns a streamed `text/plain` response containing the generated text. Invalid input returns `400`; Ollama failures return `502` with `{ "error": "..." }`.

## Project Structure

```
app.py                Flask server; proxies chat requests to Ollama
templates/index.html  Chat frontend
static/vendor/        Bundled marked, DOMPurify, highlight.js (offline)
requirements.txt      Python dependencies
```

## Configuration (environment variables)

| Variable          | Default                   | Purpose                        |
| ----------------- | ------------------------- | ------------------------------ |
| `OLLAMA_BASE_URL` | `http://localhost:11434`  | Where Ollama is running        |
| `DEFAULT_MODEL`   | `llama3:latest`           | Model used when none is given  |
| `KEEP_ALIVE`      | `30m`                     | How long Ollama keeps it loaded|
| `HOST` / `PORT`   | `127.0.0.1` / `5000`      | Server bind address            |
| `FLASK_DEBUG`     | unset                     | Set to `1` to enable debug mode|

The system prompt is the `SYSTEM_MESSAGE` constant in `app.py`.
