"""
Structured prompts for Phase 5: entity extraction, sentiment, commitment detection.
All return JSON for parsing. Used with Claude Haiku (high-frequency).
"""

# ---- Entity & topic extraction ----
SYSTEM_EXTRACTION = """You are a precise extraction assistant. Analyze the given message (email or chat) and output valid JSON only, no markdown or explanation.

Output a single JSON object with these keys:
- "summary": string, one short sentence summarizing the message (max 200 chars).
- "topics": array of strings, 1-5 topic labels (e.g. "meeting", "project update", "question", "thanks").
- "entities_mentioned": array of objects, each: {"type": "person"|"org"|"product"|"date"|"place"|"other", "value": string}.
- "has_question": boolean, true if the message asks a direct question that expects an answer.

Rules: Output only the JSON object. No code block, no extra text."""

USER_EXTRACTION_TEMPLATE = """Message to analyze:

Subject: {subject}

Body:
{body}"""


# ---- Sentiment ----
SYSTEM_SENTIMENT = """You analyze the tone and sentiment of a short message. Output valid JSON only.

Output a single JSON object with:
- "label": one of "positive", "neutral", "negative", "mixed".
- "score": number from -1.0 (most negative) to 1.0 (most positive).
- "brief_reason": one short phrase explaining the tone (e.g. "friendly thanks", "frustrated request").

Output only the JSON object. No markdown, no explanation."""

USER_SENTIMENT_TEMPLATE = """Message:

Subject: {subject}

Body:
{body}"""


# ---- Commitment detection ----
SYSTEM_COMMITMENTS = """You detect commitments and promises in messages (e.g. "I'll send it by Friday", "Let's meet next week").

Output valid JSON only. Single object with:
- "has_commitment": boolean.
- "commitments": array of objects (empty if none), each:
  - "description": string, short normalized description of the commitment.
  - "raw_text": string, exact phrase from the message.
  - "direction": "outbound" (author commits to do something) or "inbound" (someone else committed to the author).
  - "deadline_raw": string or null, any mentioned time/date as written (e.g. "by Friday", "next week").
  - "deadline_type": "date"|"relative"|"unspecified"|null.
  - "confidence": number 0.0-1.0.

Output only the JSON object. No markdown."""

USER_COMMITMENTS_TEMPLATE = """Message:

From: {sender}
Subject: {subject}
Direction: {direction}

Body:
{body}"""


def build_extraction_user(subject: str | None, body: str | None) -> str:
    return USER_EXTRACTION_TEMPLATE.format(
        subject=subject or "(no subject)",
        body=(body or "")[:12000],
    )


def build_sentiment_user(subject: str | None, body: str | None) -> str:
    return USER_SENTIMENT_TEMPLATE.format(
        subject=subject or "(no subject)",
        body=(body or "")[:8000],
    )


def build_commitments_user(sender: str | None, subject: str | None, direction: str, body: str | None) -> str:
    return USER_COMMITMENTS_TEMPLATE.format(
        sender=sender or "(unknown)",
        subject=subject or "(no subject)",
        direction=direction or "inbound",
        body=(body or "")[:12000],
    )
