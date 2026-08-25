from flask import Flask, request, Response, render_template
from flask_cors import CORS
import requests
import json

app = Flask(__name__)
CORS(app)

OLLAMA_API_URL = "http://localhost:11434/api/chat"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    messages = data.get("messages", []) 
    model = data.get("model", "llama3:latest")
    print("Selected model:", model)

    def generate():
        with requests.post(
            OLLAMA_API_URL,
            json={
                "model": model,
                "messages": messages,
                "stream": True
            },
            stream=True
        ) as response:

            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))

                    if "message" in chunk:
                        content = chunk["message"].get("content", "")
                        yield content

    return Response(generate(), content_type="text/plain")

if __name__ == "__main__":
    app.run(debug=True, threaded=True)