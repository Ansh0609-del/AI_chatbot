# chatbot.py - Google Gemini API integration for AI Study Assistant
#
# All AI calls in the application route through this module. Replaces the
# previous local Ollama/Llama 3 integration with Google's hosted Gemini API,
# which has a free tier (no credit card required) accessed via an API key
# stored in the GEMINI_API_KEY environment variable.
#
# SDK: google-genai (the current, actively maintained Google AI SDK).
# The older `google-generativeai` package is deprecated — do not use it.

import json
import logging
import os
import re
import time

from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

# Model selection. gemini-2.5-flash is the stable, free-tier model with the
# best balance of quality/speed/quota for this app's workload. It can be
# overridden via env var without a code change (e.g. to gemini-2.5-flash-lite
# for higher request-per-minute headroom on the free tier).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# How many times to retry a Gemini call on transient errors (rate limit /
# server overload) before giving up and returning a friendly error string.
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 2

_client = None  # lazily-created singleton genai.Client


def _get_client() -> genai.Client | None:
    """
    Return a cached genai.Client, creating it on first use.
    Returns None if no API key is configured so callers can fail gracefully
    instead of raising on import/startup (important for a clean /health check).
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY is not set. AI features will be unavailable.")
        return None

    try:
        _client = genai.Client(api_key=api_key)
        return _client
    except Exception:
        logger.exception("Failed to initialize Gemini client.")
        return None


# ─── Low-level Gemini wrappers ─────────────────────────────────────────────────

def _generate(prompt: str, system: str = "", json_mode: bool = False) -> str:
    """
    Send a single-turn prompt to Gemini and return the text response.
    Retries transient failures with exponential backoff.
    Returns a user-facing "⚠️ ..." string on unrecoverable failure so the
    Flask routes can return it without crashing.
    """
    client = _get_client()
    if client is None:
        return "⚠️ AI is not configured. Set the GEMINI_API_KEY environment variable."

    config_kwargs = {"system_instruction": system} if system else {}
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            text = (response.text or "").strip()
            if not text:
                logger.warning("Gemini returned an empty response for a generate call.")
            return text
        except APIError as e:
            last_error = e
            status = getattr(e, "code", None)
            # 429 = rate limited, 503 = overloaded — both worth a retry.
            if status in (429, 503) and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    "Gemini API error %s on attempt %d, retrying in %ds...",
                    status, attempt + 1, wait,
                )
                time.sleep(wait)
                continue
            logger.error("Gemini API error: %s", e)
            break
        except Exception as e:
            last_error = e
            logger.exception("Unexpected error calling Gemini API.")
            break

    if last_error and "429" in str(last_error):
        return "⚠️ Gemini quota exceeded. Please try again later."

    return "⚠️ AI service is temporarily unavailable."


def _generate_chat(messages: list[dict], system: str = "") -> str:
    """
    Send a multi-turn conversation to Gemini using its chat history format.
    messages: list of {"role": "user"|"assistant", "content": "..."}
    Gemini expects role "model" instead of "assistant", and a `parts` list,
    so we translate our internal format to the SDK's `types.Content` objects.
    """
    client = _get_client()
    if client is None:
        return "⚠️ AI is not configured. Set the GEMINI_API_KEY environment variable."

    # Translate our {role, content} history into Gemini's expected format.
    # The most recent message is the new user turn; everything before it is history.
    history = []
    for m in messages[:-1]:
        role = "model" if m["role"] == "assistant" else "user"
        history.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))

    last_message = messages[-1]["content"] if messages else ""

    config = types.GenerateContentConfig(system_instruction=system) if system else None

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            chat = client.chats.create(model=GEMINI_MODEL, history=history, config=config)
            response = chat.send_message(last_message)
            text = (response.text or "").strip()
            if not text:
                logger.warning("Gemini returned an empty response for a chat call.")
            return text
        except APIError as e:
            last_error = e
            status = getattr(e, "code", None)
            if status in (429, 503) and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    "Gemini API error %s on chat attempt %d, retrying in %ds...",
                    status, attempt + 1, wait,
                )
                time.sleep(wait)
                continue
            logger.error("Gemini API error during chat: %s", e)
            break
        except Exception as e:
            last_error = e
            logger.exception("Unexpected error calling Gemini chat API.")
            break

    if last_error and "429" in str(last_error):
        return "⚠️ Gemini quota exceeded. Please try again later."

    return "⚠️ AI service is temporarily unavailable."


def check_ai_status() -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        return {
            "running": False,
            "model_available": False,
            "message": "GEMINI_API_KEY is not set."
        }

    return {
        "running": True,
        "model_available": True,
        "message": f"Gemini configured ✅ ({GEMINI_MODEL})"
    }


# ─── Study workflow AI calls ──────────────────────────────────────────────────
# (Unchanged signatures from the Ollama version — only the underlying call swapped.)

def generate_explanation(topic: str) -> str:
    """Generate a beginner-friendly explanation of a topic (2-3 paragraphs)."""
    prompt = (
        f"Explain '{topic}' clearly for a student who is learning it for the first time. "
        "Use simple language, one or two relatable analogies, and keep it to 2-3 short paragraphs. "
        "Do not use markdown headers. Write in plain prose."
    )
    return _generate(prompt, system="You are a patient, expert tutor.")


def generate_study_notes(topic: str, explanation: str) -> str:
    """
    Generate structured study notes as bullet points.
    Passes the explanation as context so notes stay consistent.
    """
    prompt = (
        f"Based on this explanation of '{topic}':\n\n{explanation}\n\n"
        "Create concise study notes with the following sections:\n"
        "KEY CONCEPTS (5-7 bullet points)\n"
        "IMPORTANT TERMS (3-5 definitions)\n"
        "QUICK TIPS (2-3 memory tricks or shortcuts)\n\n"
        "Use plain text with dashes for bullets. No markdown."
    )
    return _generate(prompt, system="You are a concise, organized study note writer.")


def generate_quiz_questions(topic: str, notes: str) -> list[dict]:
    """
    Generate exactly 5 multiple-choice quiz questions.
    Returns a list of dicts: {question, options: [A,B,C,D], answer, explanation}
    Falls back to a safe empty list on parse failure.
    """
    prompt = (
        f"Create exactly 5 multiple-choice quiz questions about '{topic}' "
        f"based on these study notes:\n\n{notes}\n\n"
        "Return ONLY a JSON array. Each object must have:\n"
        '  "question": "...",\n'
        '  "options": ["A) ...", "B) ...", "C) ...", "D) ..."],\n'
        '  "answer": "A" (just the letter),\n'
        '  "explanation": "Why this answer is correct in one sentence."\n\n'
        "No extra text before or after the JSON array."
    )
    # json_mode=True asks Gemini to return valid JSON directly, which is far
    # more reliable than asking nicely in the prompt alone.
    raw = _generate(
        prompt, system="You are a quiz generator. Output only valid JSON.", json_mode=True
    )

    # Strip any accidental markdown fences (Gemini occasionally adds them anyway)
    raw = re.sub(r"```json|```", "", raw).strip()

    # Attempt to extract JSON array even if there's surrounding text
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        raw = match.group(0)

    try:
        questions = json.loads(raw)
        # Validate structure
        validated = []
        for q in questions[:5]:
            if all(k in q for k in ("question", "options", "answer", "explanation")):
                validated.append(q)
        return validated
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse quiz JSON from Gemini response: %r", raw[:300])
        return []


def evaluate_quiz_answers(
    topic: str, questions: list[dict], user_answers: list[str]
) -> dict:
    """
    Score a completed quiz and return feedback.
    Returns: {score, total, percentage, correct_answers, per_question_feedback, overall_feedback}
    """
    correct_answers = [q["answer"].strip().upper()[0] for q in questions]
    score = sum(
        1
        for ua, ca in zip(user_answers, correct_answers)
        if ua.strip().upper()[:1] == ca
    )
    total = len(questions)
    percentage = round(score / total * 100) if total else 0

    # Build a per-question summary string for AI feedback
    summary_lines = []
    for i, (q, ua, ca) in enumerate(zip(questions, user_answers, correct_answers), 1):
        status = "✓" if ua.strip().upper()[:1] == ca else "✗"
        summary_lines.append(
            f"Q{i}: {q['question']}\n"
            f"  User answered: {ua}  Correct: {ca}  {status}\n"
            f"  Explanation: {q.get('explanation', '')}"
        )
    summary = "\n".join(summary_lines)

    feedback_prompt = (
        f"A student just took a quiz on '{topic}' and scored {score}/{total} ({percentage}%).\n\n"
        f"Quiz summary:\n{summary}\n\n"
        "Write 2-3 sentences of encouraging, specific feedback. "
        "Point out what they did well and what to review. "
        "End with one concrete next-step recommendation."
    )
    overall_feedback = _generate(
        feedback_prompt, system="You are a supportive study coach."
    )

    return {
        "score": score,
        "total": total,
        "percentage": percentage,
        "correct_answers": correct_answers,
        "per_question_feedback": [
            {
                "question": q["question"],
                "user_answer": ua,
                "correct_answer": ca,
                "is_correct": ua.strip().upper()[:1] == ca,
                "explanation": q.get("explanation", ""),
            }
            for q, ua, ca in zip(questions, user_answers, correct_answers)
        ],
        "overall_feedback": overall_feedback,
    }


def generate_next_study_recommendation(
    user_name: str,
    studied_topics: list[str],
    weak_topics: list[str],
    last_topic: str,
    last_score_pct: float,
) -> str:
    """Suggest what the student should study next based on their history."""
    studied_str = ", ".join(studied_topics[-5:]) if studied_topics else "nothing yet"
    weak_str = ", ".join(weak_topics[:3]) if weak_topics else "none identified"

    prompt = (
        f"Student: {user_name}\n"
        f"Recently studied: {studied_str}\n"
        f"Last topic: {last_topic} (score: {last_score_pct:.0f}%)\n"
        f"Weak areas: {weak_str}\n\n"
        "In 2-3 sentences, recommend what this student should study next and why. "
        "Be specific — name actual topics or sub-topics. Be encouraging."
    )
    return _generate(prompt, system="You are a personalized study advisor.")


# ─── Chat assistant ───────────────────────────────────────────────────────────

def chat_with_assistant(
    user_message: str,
    chat_history: list[dict],
    user_context: dict,
) -> str:
    """
    Multi-turn study chatbot.
    user_context: {name, topics_studied, weak_topics, avg_score}
    chat_history: list of {role, content} dicts (role is 'user' or 'assistant')
    """
    # Build a rich system prompt that gives the AI memory of the student
    topics_str = (
        ", ".join(user_context.get("topics_studied", [])[-8:]) or "none yet"
    )
    weak_str = (
        ", ".join([t["topic"] for t in user_context.get("weak_topics", [])[:3]]) or "none"
    )
    avg_score = user_context.get("avg_score", 0)

    system = (
        f"You are a friendly, expert AI study assistant. "
        f"You are talking to {user_context.get('name', 'a student')}.\n\n"
        f"What you know about this student:\n"
        f"- Topics they have studied: {topics_str}\n"
        f"- Their weak areas: {weak_str}\n"
        f"- Average quiz score: {avg_score:.1f}%\n\n"
        "Your job is to help them learn, answer questions clearly, and encourage them. "
        "Keep responses concise but thorough. "
        "If they ask about a topic they've studied before, refer to their prior work."
    )

    # Combine history with the new user message
    messages = list(chat_history)
    messages.append({"role": "user", "content": user_message})

    return _generate_chat(messages, system=system)