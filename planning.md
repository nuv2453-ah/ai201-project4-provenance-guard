# Provenance Guard — Planning

## Architecture

### Submission Flow

    POST /submit
        -> llm_signal()         [Groq: semantic/stylistic assessment -> float 0-1]
        -> stylometric_signal() [heuristics: sentence variance + TTR -> float 0-1]
        -> combine_signals()    [weighted avg: LLM x0.6 + stylo x0.4 -> confidence]
        -> make_label()         [confidence -> plain-language transparency label]
        -> append_log()         [structured JSON audit entry]
        -> JSON response        [content_id, attribution, confidence, scores, label]

### Appeal Flow

    POST /appeal
        -> lookup content_id in log.json
        -> update status to "under_review"
        -> store appeal_reasoning + appeal_timestamp
        -> JSON response        [confirmation]

### API Surface

- POST /submit -- accepts {text, creator_id}, returns {content_id, attribution, confidence, llm_score, stylo_score, label, timestamp}
- POST /appeal -- accepts {content_id, creator_reasoning}, returns {message, content_id, status}
- GET /log -- returns last 20 audit log entries as JSON

---

## Detection Signals

### Signal 1: LLM-based classification (Groq, llama-3.3-70b-versatile)
- What it measures: Holistic semantic and stylistic coherence. The model assesses whether the text reads as AI-generated based on patterns in word choice, sentence construction, and rhetorical flow.
- Output: Float 0.0-1.0 (0 = definitely human, 1 = definitely AI)
- Blind spot: LLMs can be fooled by lightly edited AI output or highly polished human prose. A human writer who naturally uses formal academic register may score higher than expected.

### Signal 2: Stylometric heuristics (pure Python)
- What it measures: Two structural properties -- sentence length variance (AI text tends to be more uniform) and type-token ratio (lexical diversity; AI text tends to be slightly less varied).
- Output: Float 0.0-1.0 (0 = high variance/diversity -> human-like, 1 = low variance/diversity -> AI-like)
- Blind spot: Short texts do not have enough sentences for variance to be meaningful. Very casual human writing with limited vocabulary may score as AI-like on TTR.

### Combining Signals
Weighted average: confidence = llm_score x 0.6 + stylo_score x 0.4

The LLM signal gets higher weight because it captures semantic patterns that the structural heuristics miss. The stylometric signal acts as a check -- if the LLM says AI but the structure looks highly variable and diverse, the combined score moderates toward uncertainty.

---

## Uncertainty Representation

| Confidence range | Attribution  | Label category        |
|------------------|--------------|-----------------------|
| < 0.35           | likely_human | High-confidence human |
| 0.35 - 0.65      | uncertain    | Uncertain             |
| > 0.65           | likely_ai    | High-confidence AI    |

A score of 0.6 means the system leans toward AI but not strongly enough to label it as such -- the label will say uncertain and prompt the creator to appeal if they disagree. This reflects the asymmetry in false positive cost: mislabeling a human writer's work as AI is worse than missing an AI submission.

---

## Transparency Label Variants

High-confidence AI (confidence > 0.65):
"AI-Generated Content: Our system is fairly confident this content was produced with AI assistance. If you created this yourself, you can submit an appeal below."

Uncertain (0.35 to 0.65):
"Attribution Uncertain: Our system couldn't determine with confidence whether this content is human-written or AI-generated. The author's attribution is shown as-is. If you believe this label is wrong, you can submit an appeal."

High-confidence human (confidence < 0.35):
"Human-Written Content: Our system is fairly confident this content was written by a person. Attribution looks good."

---

## Appeals Workflow

- Any creator can submit an appeal via POST /appeal with their content_id and a free-text creator_reasoning field.
- The system updates the content's status from classified to under_review in the audit log and stores the reasoning and a timestamp.
- No automated re-classification occurs. A human reviewer would open GET /log, filter for status: under_review, and read the appeal_reasoning alongside the original signal scores to make a judgment.

---

## Anticipated Edge Cases

1. Non-native English speakers with formal writing styles: A human writer who naturally constructs grammatically precise, low-variance sentences may score high on both signals, producing a false positive. The system partially mitigates this by keeping the uncertain band wide (0.35-0.65), but a formal non-native writer could still cross the 0.65 threshold.

2. Very short texts (under 3 sentences): The stylometric signal degrades significantly with short input -- sentence length variance is meaningless with one or two sentences, and TTR is unreliable on small word counts. The system returns 0.5 as a fallback for short texts, pushing them into the uncertain band.

---

## AI Tool Plan

### M3 -- Submission endpoint + first signal
- Spec sections provided: Detection signals section + architecture diagram
- What I asked for: Flask app skeleton with POST /submit route stub + llm_signal() function
- Verification: Called llm_signal() directly on test inputs before wiring into endpoint; checked that return value was a float between 0 and 1

### M4 -- Second signal + confidence scoring
- Spec sections provided: Detection signals + uncertainty representation + architecture diagram
- What I asked for: stylometric_signal() function + combine_signals() logic matching the 60/40 weighting in the spec
- Verification: Tested on four inputs (clearly AI, clearly human, two borderline); confirmed scores varied meaningfully

### M5 -- Production layer
- Spec sections provided: Label variants + appeals workflow + architecture diagram
- What I asked for: make_label() function + POST /appeal endpoint
- Verification: Confirmed all three label variants were reachable; confirmed appeal updated status and appeared in log
