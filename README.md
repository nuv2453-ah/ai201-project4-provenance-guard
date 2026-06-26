# Provenance Guard

A backend attribution system for creative content platforms. Classifies submitted text as likely AI-generated or likely human-written, scores confidence, surfaces a transparency label, and handles creator appeals.

## Architecture Overview

A submitted piece of text takes the following path:

1. POST /submit receives text and creator_id
2. Signal 1 — LLM classification: the text is sent to Groq (llama-3.3-70b-versatile) with a structured prompt asking for an AI probability score (0-1) and reasoning
3. Signal 2 — Stylometric heuristics: pure Python computes sentence length variance, type-token ratio, and punctuation density, combining them into a second AI probability score
4. Confidence scoring: the two scores are combined (65% LLM weight + 35% stylometric weight) into a single confidence value
5. Transparency label: the confidence value maps to one of three label variants shown to the reader
6. Audit log: a structured JSON entry is written capturing all scores, attribution, and timestamp
7. Response: the caller receives content_id, attribution, confidence, both signal scores, label, and status

## Detection Signals

### Signal 1: LLM Classification (Groq)
Sends the text to llama-3.3-70b-versatile and asks it to return a structured JSON assessment of AI probability. This captures holistic properties — tone uniformity, vocabulary choices, emotional authenticity, natural imperfections — that are hard to measure statistically.

What it misses: Short texts give the model little signal. Heavily edited AI output can fool it. Formal human writing (academic essays, legal documents) may score falsely high.

### Signal 2: Stylometric Heuristics
Computes three statistical properties in pure Python:
- Sentence length variance — AI text tends to be more uniform; human writing varies more
- Type-token ratio — unique words divided by total words; AI text tends toward moderate, consistent vocabulary
- Punctuation density — AI text uses punctuation moderately and consistently

These three sub-scores are weighted into a single 0-1 signal (variance 50%, TTR 30%, punctuation 20%).

What it misses: Texts under 3 sentences lack enough data for meaningful variance. Non-native English speakers often produce low-variance writing. Poetry and intentionally repetitive styles score as AI-like regardless of origin.

## Confidence Scoring

Combined confidence = (llm_score x 0.65) + (stylo_score x 0.35)

Thresholds:
- >= 0.75 → likely_ai
- 0.36-0.74 → uncertain
- <= 0.35 → likely_human

The LLM signal is weighted higher because it captures semantic properties the stylometric signal cannot. The threshold for likely_ai is deliberately set high at 0.75 — mislabeling a human's work as AI is worse than missing AI-generated content, so we bias toward uncertainty.

Example submissions with different confidence scores:

High-confidence AI text:
"Artificial intelligence represents a transformative paradigm shift in modern society..."
→ llm_score: 0.92, stylo_score: 0.246, confidence: 0.684 (uncertain — signals disagree on this borderline case)

Clearly human text:
"ok so i finally tried that new ramen place downtown and honestly? underwhelming..."
→ llm_score: 0.21, stylo_score: 0.175, confidence: 0.198 (likely_human)

## Transparency Label

All three variants written out exactly as displayed to users:

High-confidence AI (confidence >= 0.75):
"This content shows strong indicators of AI generation (confidence: X%). This assessment is automated and may not be fully accurate. If you believe this is incorrect, you may submit an appeal."

Uncertain (confidence 0.36-0.74):
"Our system is uncertain about the origin of this content (AI likelihood: X%). The writing shows mixed signals. Human and AI-assisted content can both appear here. The creator may submit an appeal to provide more context."

High-confidence human (confidence <= 0.35):
"This content shows strong indicators of human authorship (confidence: X%). Our system found natural variation and stylistic patterns consistent with human writing."

## Rate Limiting

Limits applied to POST /submit: 10 requests per minute, 100 requests per day per IP address.

Reasoning: A real writer submitting their own work would rarely need more than 2-3 submissions in a session — 10/minute is generous for legitimate use while stopping burst flooding. 100/day prevents scripts that space out requests across a full day. These limits also protect Groq API costs since each submission makes one LLM call.

Rate limit test results (12 rapid requests — 10 succeed, 2 blocked):
200
200
200
200
200
200
200
200
200
200
429
429

## Audit Log

Every submission and appeal is logged to audit_log.json. Sample from GET /log:

Entry 1 (submission with appeal):
- content_id: 6583afcf-72be-452e-9978-91a5f0011338
- creator_id: test-user-1
- timestamp: 2026-06-26T04:04:07.249116+00:00
- attribution: uncertain
- confidence: 0.684
- llm_score: 0.92
- stylo_score: 0.246
- status: under_review
- appeal reasoning: "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."
- appeal submitted_at: 2026-06-26T04:05:25.205779+00:00

Entry 2 (submission, no appeal):
- content_id: e80f2c7d-f509-4107-b0c9-1e24df993d59
- creator_id: test-user-2
- timestamp: 2026-06-26T04:05:11.241955+00:00
- attribution: likely_human
- confidence: 0.198
- llm_score: 0.21
- stylo_score: 0.175
- status: classified
- appeal: null

## Known Limitations

Non-native English speakers are the most likely false positive group. Formal, low-variance writing patterns common among non-native speakers look statistically similar to AI output on both signals. The stylometric signal penalizes low sentence length variance regardless of cause, and the LLM signal may interpret formal non-native phrasing as AI-generated. The appeals workflow is the primary correction path for this group.

## Spec Reflection

How the spec helped: Writing out the three label variants in planning.md before touching any code forced a concrete decision about what 0.6 confidence actually means to a user. Without that, the label would have been an afterthought built around the score rather than designed for a reader.

Where implementation diverged: The spec assumed the stylometric signal would be a reliable second signal across all text lengths. In practice, texts under 3 sentences produce meaningless variance scores — the signal defaults to 0.5 and contributes noise. I added a minimum sentence check to handle this, which was not in the original plan.

## AI Usage

Instance 1: I provided the detection signals section and architecture diagram and asked Claude to generate the Flask app skeleton and Groq LLM signal function. The generated function returned a raw string instead of parsed JSON and did not strip markdown code fences that Groq sometimes wraps around responses. I added a re.sub call to strip fences before parsing, and verified the output format independently before wiring it into the endpoint.

Instance 2: I asked Claude to generate the stylometric signal function and confidence scoring logic. The generated scoring function used equal 50/50 weighting for both signals. I overrode this to 65/35 (LLM-weighted) based on my judgment that the LLM signal captures more meaningful semantic properties and the stylometric signal is unreliable on short texts. I also adjusted the variance normalization divisor after testing showed the default made all texts cluster near 0.5.
