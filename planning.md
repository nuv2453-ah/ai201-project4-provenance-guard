# Provenance Guard — Planning

## Architecture

Submission Flow:
POST /submit
  → validate input (text, creator_id)
  → Signal 1: LLM classification (Groq llama-3.3-70b-versatile)
      outputs: ai_probability (0.0-1.0), reasoning string
  → Signal 2: Stylometric heuristics (pure Python)
      outputs: ai_probability (0.0-1.0) from sentence variance, TTR, punctuation density
  → Confidence scoring: weighted average (65% LLM + 35% stylometric)
  → Transparency label: mapped from confidence score
  → Audit log: write structured JSON entry
  → Return JSON response

Appeal Flow:
POST /appeal
  → validate input (content_id, creator_reasoning)
  → look up content_id in audit log
  → update status to "under_review"
  → append appeal object (reasoning, timestamp)
  → write updated log
  → return confirmation JSON

## Detection Signals

### Signal 1: LLM Classification (Groq)
- What it measures: Holistic semantic and stylistic coherence. The model assesses tone, sentence uniformity, vocabulary choice, emotional authenticity, and natural imperfections.
- Output: Float 0.0-1.0 (ai_probability) + reasoning string
- Blind spots: Short texts give the LLM little to work with. Heavily edited AI output may fool it. Highly polished human writing (academic papers, formal essays) may score falsely high.

### Signal 2: Stylometric Heuristics (pure Python)
- What it measures: Statistical structural properties of text.
  - Sentence length variance (AI text is more uniform)
  - Type-token ratio / vocabulary diversity (unique words / total words)
  - Punctuation density (AI text tends toward moderate, consistent punctuation)
- Output: Float 0.0-1.0 (ai_probability)
- Blind spots: Short texts have too few sentences for meaningful variance. Non-native English speakers often write with lower variance. Poetry and intentionally repetitive writing will score as AI-like.

## Uncertainty Representation

Combined confidence = (llm_score x 0.65) + (stylo_score x 0.35)

Thresholds:
- confidence >= 0.75 → attribution: "likely_ai" → high-confidence AI label
- confidence 0.36-0.74 → attribution: "uncertain" → uncertain label
- confidence <= 0.35 → attribution: "likely_human" → high-confidence human label

A score of 0.6 means the system leans toward AI but not with enough confidence to make a strong claim. The threshold for "likely_ai" is deliberately high (0.75) because false positives — mislabeling human work as AI — are worse than false negatives on a creative platform.

## Transparency Label Variants

High-confidence AI (confidence >= 0.75):
"This content shows strong indicators of AI generation (confidence: X%). This assessment is automated and may not be fully accurate. If you believe this is incorrect, you may submit an appeal."

Uncertain (confidence 0.36-0.74):
"Our system is uncertain about the origin of this content (AI likelihood: X%). The writing shows mixed signals. Human and AI-assisted content can both appear here. The creator may submit an appeal to provide more context."

High-confidence human (confidence <= 0.35):
"This content shows strong indicators of human authorship (confidence: X%). Our system found natural variation and stylistic patterns consistent with human writing."

## Appeals Workflow

- Any creator can submit an appeal by providing their content_id and a written explanation
- On appeal submission: status updates to "under_review", appeal object (reasoning + timestamp) appended to audit log entry
- A human reviewer would use GET /log to see all entries with status "under_review"
- Automated re-classification is not performed

## Anticipated Edge Cases

1. Non-native English speakers with formal writing styles: Uniform sentence structure and limited vocabulary diversity are common in non-native writing, which both signals may interpret as AI-like. The appeals workflow is the intended correction path.

2. Short texts (under 3 sentences): The stylometric signal requires multiple sentences to compute meaningful variance. For very short texts it defaults to 0.5 (neutral), making the LLM signal dominate entirely.

## Rate Limiting

Limits: 10 requests per minute, 100 per day per IP address.

Reasoning: A real writer submitting their own work would rarely need more than 2-3 submissions per session. 10/minute is generous for legitimate use. 100/day prevents automated scripts from spacing out requests. These limits also protect Groq API costs since each submission makes one LLM call.

## API Endpoints

- POST /submit — accepts {text, creator_id}, returns {content_id, attribution, confidence, llm_score, stylo_score, label, status}
- POST /appeal — accepts {content_id, creator_reasoning}, returns {content_id, status, message}
- GET /log — returns last 20 audit log entries as JSON

## AI Tool Plan

### M3 (submission endpoint + first signal)
- Provide: detection signals section + architecture diagram
- Ask for: Flask app skeleton with POST /submit stub + Groq LLM signal function
- Verify: function returns a float 0-1, route accepts correct JSON fields, test independently before wiring in

### M4 (second signal + confidence scoring)
- Provide: detection signals + uncertainty representation sections + diagram
- Ask for: stylometric signal function + weighted scoring logic
- Verify: scores vary meaningfully between clearly AI and clearly human text; thresholds match planning.md

### M5 (production layer)
- Provide: label variants + appeals workflow + diagram
- Ask for: label generation function + POST /appeal endpoint
- Verify: all 3 label variants reachable at different score ranges; appeal updates status in log
