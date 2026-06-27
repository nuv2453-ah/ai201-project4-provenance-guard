# Provenance Guard

A backend attribution analysis system for creative content platforms. Any platform where people share original writing, music descriptions, or blog posts can plug in this API to classify submitted content, score confidence in that classification, surface a transparency label to readers, and handle appeals from creators who believe they've been misclassified.

---

## Architecture Overview

A submitted piece of text travels through the following path:

POST /submit receives {text, creator_id} -> the LLM signal sends the text to Groq and gets back an AI-probability float -> the stylometric signal computes sentence length variance and type-token ratio and produces a second float -> combine_signals() takes a weighted average (LLM x0.6, stylometric x0.4) to produce a single confidence score -> make_label() maps that score to one of three plain-language transparency labels -> the result is written as a structured entry to log.json -> the full response (including content_id, scores, attribution, and label text) is returned to the caller.

The appeal flow is separate: POST /appeal receives a content_id and the creator's reasoning, looks up the original entry in the log, updates its status to under_review, and stores the reasoning alongside the original decision.

---

## Detection Signals

### Signal 1: LLM-based classification
The text is sent to llama-3.3-70b-versatile via Groq with a prompt asking it to estimate the probability that the content is AI-generated. This captures holistic semantic and stylistic patterns -- word choice, rhetorical structure, tonal uniformity -- that are difficult to reduce to simple statistics.

Output: Float 0.0-1.0

What it misses: Lightly edited AI output that has been humanized, and formally written human prose that happens to use consistent vocabulary and sentence structure. A skilled academic writer may score unexpectedly high on this signal.

### Signal 2: Stylometric heuristics
Two structural properties are computed in pure Python: sentence length variance (AI text tends to produce more uniform sentence lengths) and type-token ratio, or TTR (unique words / total words -- AI text tends to be slightly less lexically diverse). These are averaged into a single signal score.

Output: Float 0.0-1.0

What it misses: Short texts (fewer than 3 sentences) don't produce meaningful variance. Very casual human writing with limited vocabulary can score as AI-like on TTR despite being clearly human.

---

## Confidence Scoring

The two signal scores are combined as a weighted average: confidence = llm_score x 0.6 + stylo_score x 0.4. The LLM signal gets higher weight because it captures semantic-level patterns the heuristics cannot reach. The stylometric signal acts as a structural check -- when the two signals disagree strongly, the combined score moderates toward the uncertain range rather than committing to either label.

Thresholds:
- confidence < 0.35 -> likely_human
- 0.35 to 0.65 -> uncertain
- confidence > 0.65 -> likely_ai

Example submissions from testing:

Clearly AI-generated text ("paradigm shift... stakeholders across various sectors"):
- LLM score: 0.800, stylometric score: 0.131, combined confidence: 0.532 -> uncertain
- The LLM recognized AI-like phrasing but the stylometric signal found high sentence variance, pulling the score into the uncertain range.

Casual human writing (ramen restaurant complaint):
- LLM score: 0.200, stylometric score: 0.000, combined confidence: 0.120 -> likely_human
- Both signals agreed strongly: low AI probability from the LLM, and stylometric found high lexical diversity and sentence irregularity.

---

## Transparency Label

All three label variants, written out exactly as they appear in API responses:

High-confidence AI (confidence > 0.65):
"AI-Generated Content: Our system is fairly confident this content was produced with AI assistance. If you created this yourself, you can submit an appeal below."

Uncertain (0.35 to 0.65):
"Attribution Uncertain: Our system couldn't determine with confidence whether this content is human-written or AI-generated. The author's attribution is shown as-is. If you believe this label is wrong, you can submit an appeal."

High-confidence human (confidence < 0.35):
"Human-Written Content: Our system is fairly confident this content was written by a person. Attribution looks good."

---

## Rate Limiting

The POST /submit endpoint is limited to 10 requests per minute per IP address.

Reasoning: A real creator submitting their own work rarely needs to submit more than a few pieces in a short window -- 10 per minute is generous for legitimate use. The tighter constraint matters on the adversarial side: a script trying to probe the classifier or flood the system with submissions would hit the limit almost immediately.

Evidence (status codes from 12 rapid submissions):
200 200 200 200 200 200 200 200 200 200 429 429

---

## Audit Log

Every attribution decision is written to log.json as a structured entry. The log captures: content_id, creator_id, timestamp, attribution, confidence, llm_score, stylo_score, status, and appeal_reasoning (null until an appeal is filed).

Sample entries from GET /log:

Entry 1 -- human writing with filed appeal:
  content_id: 85b58918-88ce-4aa5-8f97-aac470fa87da
  creator_id: test-user-1
  timestamp: 2026-06-27T03:34:17.984138+00:00
  attribution: likely_human
  confidence: 0.319
  llm_score: 0.2
  stylo_score: 0.497
  status: under_review
  appeal_reasoning: "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."

Entry 2 -- AI-sounding text, uncertain verdict:
  content_id: fa2b7a36-dc80-4468-8fe0-0c102021b437
  creator_id: test-user-2
  timestamp: 2026-06-27T03:38:32.130985+00:00
  attribution: uncertain
  confidence: 0.532
  llm_score: 0.8
  stylo_score: 0.131
  status: classified

Entry 3 -- casual human writing, strong human verdict:
  content_id: 252a2cce-9ccb-4b60-8e70-cc7322516ff9
  creator_id: test-user-3
  timestamp: 2026-06-27T03:38:36.613257+00:00
  attribution: likely_human
  confidence: 0.12
  llm_score: 0.2
  stylo_score: 0.0
  status: classified

---

## Known Limitations

Non-native English speakers who write in a formal register are the most likely false positive case for this system. Formal human writing -- precise grammar, consistent sentence structure, limited colloquialisms -- shares surface features with AI output on both signals. The LLM may read it as AI-like stylistically, and the stylometric signal may find lower-than-average sentence length variance. The wide uncertain band (0.35-0.65) partially absorbs this, but a formal non-native writer could still cross the 0.65 threshold and receive an AI label. The appeals workflow is the primary mitigation here.

---

## Spec Reflection

The spec helped most during confidence scoring design. Writing out the three label variants before building anything forced a concrete decision about what 0.5 should mean to a user -- not just a number, but a specific label with specific language. That decision then constrained the threshold choices in a way that felt principled rather than arbitrary.

One divergence: the spec called for a daily rate limit in addition to the per-minute one. During testing, Flask-Limiter's semicolon-separated multi-limit syntax did not enforce correctly in the version installed, so the daily limit was dropped in favor of a single per-minute limit that was confirmed to work. In production, the daily limit would be worth reinstating with a proper Redis backend.

---

## AI Usage

Instance 1: I directed the AI tool to generate the Flask app skeleton -- the route stubs for POST /submit, POST /appeal, and GET /log, plus the llm_signal() function. The generated llm_signal() returned the full API response object rather than just the parsed float, so I revised it to extract parsed["ai_probability"] and cast it to float before returning.

Instance 2: I directed the AI tool to generate the stylometric_signal() function and combine_signals() weighting logic based on the spec's 60/40 weighting description. The generated function used a fixed sentence splitter that broke on texts without terminal punctuation. I overrode the splitter to use a regex that handles [.!?]+ patterns and added the short-text fallback (returning 0.5 when fewer than 2 sentences are detected).

---

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    # add your GROQ_API_KEY to .env
    flask run --port 5001

Endpoints:
- POST /submit -- {text: str, creator_id: str}
- POST /appeal -- {content_id: str, creator_reasoning: str}
- GET /log -- returns last 20 audit entries
