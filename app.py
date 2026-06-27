import os
import json
import uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
LOG_FILE = "log.json"


# ── Audit log helpers ──────────────────────────────────────────────────────────

def read_log():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE) as f:
        return json.load(f)

def write_log(entries):
    with open(LOG_FILE, "w") as f:
        json.dump(entries, f, indent=2)

def append_log(entry):
    entries = read_log()
    entries.append(entry)
    write_log(entries)


# ── Signal 1: LLM-based classification (Groq) ─────────────────────────────────

def llm_signal(text):
    """Returns a float 0-1 where 1 = very likely AI-generated."""
    prompt = (
        "You are an expert at distinguishing AI-generated text from human-written text. "
        "Analyze the following piece of writing and respond with ONLY a JSON object in this exact format:\n"
        '{"ai_probability": <float between 0.0 and 1.0>, "reasoning": "<one sentence>"}\n\n'
        "0.0 = definitely human-written, 1.0 = definitely AI-generated.\n\n"
        f"Text to analyze:\n{text}"
    )
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    raw = response.choices[0].message.content.strip()
    # strip markdown fences if present
    raw = raw.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(raw)
    return float(parsed["ai_probability"])


# ── Signal 2: Stylometric heuristics ──────────────────────────────────────────

def stylometric_signal(text):
    """
    Returns a float 0-1 where 1 = AI-like (uniform, low-variance).
    Measures:
      - sentence length variance (AI text is more uniform → lower variance → higher score)
      - type-token ratio (AI text has slightly lower lexical diversity)
      - punctuation density
    """
    import re

    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if len(sentences) < 2:
        return 0.5  # not enough data

    # Sentence length variance
    lengths = [len(s.split()) for s in sentences]
    mean_len = sum(lengths) / len(lengths)
    variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
    # High variance = human; normalize: variance > 40 → very human, < 5 → very AI
    variance_score = max(0.0, min(1.0, 1 - (variance / 40)))

    # Type-token ratio (unique words / total words)
    words = re.findall(r'\b\w+\b', text.lower())
    ttr = len(set(words)) / len(words) if words else 0.5
    # Lower TTR → more AI-like; typical human TTR ~0.6-0.8, AI ~0.4-0.6
    ttr_score = max(0.0, min(1.0, 1 - ((ttr - 0.3) / 0.5)))

    # Combine with equal weight
    return (variance_score + ttr_score) / 2


# ── Confidence scoring ─────────────────────────────────────────────────────────

def combine_signals(llm_score, stylo_score):
    """Weighted combination: LLM 60%, stylometric 40%."""
    return round(llm_score * 0.6 + stylo_score * 0.4, 3)


# ── Transparency label ─────────────────────────────────────────────────────────

def make_label(confidence):
    """
    Maps combined confidence score to a plain-language label.
    < 0.35  → high-confidence human
    0.35–0.65 → uncertain
    > 0.65  → high-confidence AI
    """
    if confidence > 0.65:
        return (
            "AI-Generated Content: Our system is fairly confident this content "
            "was produced with AI assistance. If you created this yourself, you "
            "can submit an appeal below."
        )
    elif confidence < 0.35:
        return (
            "Human-Written Content: Our system is fairly confident this content "
            "was written by a person. Attribution looks good."
        )
    else:
        return (
            "Attribution Uncertain: Our system couldn't determine with confidence "
            "whether this content is human-written or AI-generated. The author's "
            "attribution is shown as-is. If you believe this label is wrong, you "
            "can submit an appeal."
        )


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute")
def submit():
    data = request.get_json()
    text = data.get("text", "").strip()
    creator_id = data.get("creator_id", "unknown")

    if not text:
        return jsonify({"error": "text field is required"}), 400

    content_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    llm_score = llm_signal(text)
    stylo_score = stylometric_signal(text)
    confidence = combine_signals(llm_score, stylo_score)

    attribution = (
        "likely_ai" if confidence > 0.65
        else "likely_human" if confidence < 0.35
        else "uncertain"
    )
    label = make_label(confidence)

    log_entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": round(llm_score, 3),
        "stylo_score": round(stylo_score, 3),
        "status": "classified",
        "appeal_reasoning": None,
    }
    append_log(log_entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": round(llm_score, 3),
        "stylo_score": round(stylo_score, 3),
        "label": label,
        "timestamp": timestamp,
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json()
    content_id = data.get("content_id", "").strip()
    reasoning = data.get("creator_reasoning", "").strip()

    if not content_id or not reasoning:
        return jsonify({"error": "content_id and creator_reasoning are required"}), 400

    entries = read_log()
    updated = False
    for entry in entries:
        if entry["content_id"] == content_id:
            entry["status"] = "under_review"
            entry["appeal_reasoning"] = reasoning
            entry["appeal_timestamp"] = datetime.now(timezone.utc).isoformat()
            updated = True
            break

    if not updated:
        return jsonify({"error": "content_id not found"}), 404

    write_log(entries)
    return jsonify({
        "message": "Appeal received. Your content has been marked as under review.",
        "content_id": content_id,
        "status": "under_review",
    })


@app.route("/log", methods=["GET"])
def get_log():
    entries = read_log()
    return jsonify({"entries": entries[-20:]})  # return last 20


if __name__ == "__main__":
    app.run(debug=True)
