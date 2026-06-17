# app.py - Flask application entry point for AI Study Assistant
#
# Local dev:   python app.py
# Production:  gunicorn app:app   (see Procfile / render.yaml)
#
# Requires GEMINI_API_KEY to be set (see .env.example). All AI calls go
# through chatbot.py, which wraps the Google Gemini API.

import logging
import sys

from flask import Flask, request, jsonify, render_template, session

from config import Config
from database import (
    init_db,
    create_user,
    get_user,
    get_all_users,
    update_user_activity,
    save_topic,
    get_user_topics,
    save_quiz_result,
    get_user_quiz_results,
    get_weak_topics,
    save_chat_message,
    get_chat_history,
    clear_chat_history,
    get_dashboard_data,
)
from chatbot import (
    check_ai_status,
    generate_explanation,
    generate_study_notes,
    generate_quiz_questions,
    evaluate_quiz_answers,
    generate_next_study_recommendation,
    chat_with_assistant,
)

# ─── Logging setup ─────────────────────────────────────────────────────────────
# Configured before anything else so startup warnings, request errors, and
# Gemini API issues all show up consistently in Render's log viewer.

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("study_assistant")

# ─── App factory ────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.config["SESSION_COOKIE_SECURE"] = Config.SESSION_COOKIE_SECURE
app.config["SESSION_COOKIE_HTTPONLY"] = Config.SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = Config.SESSION_COOKIE_SAMESITE

for warning in Config.validate():
    logger.warning(warning)

_db_ready = False


@app.before_request
def setup():
    """Initialize DB tables before the very first request, exactly once."""
    global _db_ready
    if not _db_ready:
        init_db()
        _db_ready = True


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    """
    Catch-all so an unhandled exception in any route returns clean JSON
    instead of leaking a stack trace, while still logging full details
    server-side for debugging.
    """
    from werkzeug.exceptions import HTTPException
    if isinstance(err, HTTPException):
        return err
    logger.exception("Unhandled exception while processing %s %s", request.method, request.path)
    return jsonify({"error": "Internal server error. Please try again."}), 500


# ─── Health check (for Render / uptime monitoring) ───────────────────────────────

@app.route("/health")
def health():
    """
    Lightweight liveness/readiness probe for Render's health checks and any
    external uptime monitor. Deliberately does NOT call the Gemini API (that
    would cost quota on every health check) — it only confirms the app
    process is up and the database is reachable.
    """
    try:
        # A trivial query confirms the DB file is reachable and not corrupted.
        get_all_users()
        db_ok = True
    except Exception:
        logger.exception("Health check failed: database not reachable.")
        db_ok = False

    status = "ok" if db_ok else "degraded"
    code = 200 if db_ok else 503
    return jsonify({
        "status": status,
        "database": "ok" if db_ok else "error",
        "gemini_configured": bool(Config.GEMINI_API_KEY),
    }), code


# ─── Page routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page — user selection or creation."""
    return render_template("index.html")


@app.route("/chat")
def chat_page():
    """Main chat interface."""
    user_id = session.get("user_id")
    if not user_id:
        return render_template("index.html", error="Please select or create a profile first.")
    user = get_user(user_id)
    if not user:
        session.pop("user_id", None)
        return render_template("index.html", error="Your session expired. Please select a profile again.")
    return render_template("chat.html", user=user)


@app.route("/study")
def study_page():
    """Study workflow page (explain → notes → quiz)."""
    user_id = session.get("user_id")
    if not user_id:
        return render_template("index.html", error="Please select or create a profile first.")
    user = get_user(user_id)
    if not user:
        session.pop("user_id", None)
        return render_template("index.html", error="Your session expired. Please select a profile again.")
    return render_template("study.html", user=user)


@app.route("/dashboard")
def dashboard_page():
    """Dashboard showing progress and stats."""
    user_id = session.get("user_id")
    if not user_id:
        return render_template("index.html", error="Please select or create a profile first.")
    user = get_user(user_id)
    if not user:
        session.pop("user_id", None)
        return render_template("index.html", error="Your session expired. Please select a profile again.")
    return render_template("dashboard.html", user=user)


@app.route("/history")
def history_page():
    """Full study history page."""
    user_id = session.get("user_id")
    if not user_id:
        return render_template("index.html", error="Please select or create a profile first.")
    user = get_user(user_id)
    if not user:
        session.pop("user_id", None)
        return render_template("index.html", error="Your session expired. Please select a profile again.")
    return render_template("history.html", user=user)


# ─── User management API ──────────────────────────────────────────────────────

@app.route("/api/users", methods=["GET"])
def api_get_users():
    """List all existing user profiles."""
    return jsonify(get_all_users())


@app.route("/api/users", methods=["POST"])
def api_create_user():
    """Create a new user profile and set session."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    if len(name) > 80:
        return jsonify({"error": "Name is too long (max 80 characters)"}), 400

    user_id = create_user(name)
    session["user_id"] = user_id
    logger.info("Created new user profile: %s (id=%s)", name, user_id)
    return jsonify({"id": user_id, "name": name}), 201


@app.route("/api/users/select", methods=["POST"])
def api_select_user():
    """Select an existing user (log in)."""
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not isinstance(user_id, int):
        return jsonify({"error": "A valid user_id is required"}), 400

    user = get_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    session["user_id"] = user_id
    update_user_activity(user_id)
    return jsonify(user)


@app.route("/api/users/logout", methods=["POST"])
def api_logout():
    """Clear the current session."""
    session.pop("user_id", None)
    return jsonify({"ok": True})


@app.route("/api/users/me", methods=["GET"])
def api_current_user():
    """Return the currently logged-in user."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    user = get_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user)


# ─── Study workflow API ───────────────────────────────────────────────────────

@app.route("/api/study/start", methods=["POST"])
def api_start_study():
    """
    Full study workflow for a topic:
    1. Generate explanation
    2. Generate notes
    3. Save topic to DB
    4. Return explanation + notes + topic_id
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Topic is required"}), 400
    if len(topic) > 200:
        return jsonify({"error": "Topic is too long (max 200 characters)"}), 400

    try:
        explanation = generate_explanation(topic)
        notes = generate_study_notes(topic, explanation)
    except Exception:
        logger.exception("AI generation failed for topic: %s", topic)
        return jsonify({"error": "Failed to generate study content. Please try again."}), 502

    topic_id = save_topic(user_id, topic, explanation, notes)
    update_user_activity(user_id)

    return jsonify({
        "topic_id": topic_id,
        "topic": topic,
        "explanation": explanation,
        "notes": notes,
    })


@app.route("/api/study/quiz/generate", methods=["POST"])
def api_generate_quiz():
    """Generate 5 quiz questions for a topic (by topic_id already saved)."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    notes = (data.get("notes") or "").strip()

    if not topic:
        return jsonify({"error": "Topic is required"}), 400

    try:
        questions = generate_quiz_questions(topic, notes)
    except Exception:
        logger.exception("Quiz generation failed for topic: %s", topic)
        return jsonify({"error": "Failed to generate questions. Try again."}), 502

    if not questions:
        return jsonify({"error": "Failed to generate questions. Try again."}), 502

    return jsonify({"questions": questions})


@app.route("/api/study/quiz/submit", methods=["POST"])
def api_submit_quiz():
    """
    Evaluate submitted quiz answers and save result.
    Expects: {topic_id, topic, questions, user_answers}
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    topic_id = data.get("topic_id")
    topic = (data.get("topic") or "").strip()
    questions = data.get("questions", [])
    user_answers = data.get("user_answers", [])

    if not all([topic, questions, user_answers]):
        return jsonify({"error": "Missing required fields"}), 400
    if len(user_answers) != len(questions):
        return jsonify({"error": "Number of answers must match number of questions"}), 400

    try:
        result = evaluate_quiz_answers(topic, questions, user_answers)
    except Exception:
        logger.exception("Quiz evaluation failed for topic: %s", topic)
        return jsonify({"error": "Failed to grade quiz. Please try again."}), 502

    save_quiz_result(
        user_id=user_id,
        topic_id=topic_id,
        topic=topic,
        questions=[q["question"] for q in questions],
        answers=user_answers,
        correct_answers=result["correct_answers"],
        score=result["score"],
        feedback=result["overall_feedback"],
    )
    update_user_activity(user_id)

    # Generate next-step recommendation (best-effort — don't fail the whole
    # request if only this part of the AI call has trouble).
    try:
        topics = [t["topic"] for t in get_user_topics(user_id)]
        weak = [w["topic"] for w in get_weak_topics(user_id)]
        user = get_user(user_id)
        recommendation = generate_next_study_recommendation(
            user_name=user["name"],
            studied_topics=topics,
            weak_topics=weak,
            last_topic=topic,
            last_score_pct=result["percentage"],
        )
    except Exception:
        logger.exception("Failed to generate next-step recommendation.")
        recommendation = "Keep practicing this topic, then move on to something new!"

    result["recommendation"] = recommendation
    return jsonify(result)


# ─── Chat API ─────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    Send a message and get an AI reply.
    Maintains conversation history in DB for context.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400
    if len(message) > 4000:
        return jsonify({"error": "Message is too long (max 4000 characters)"}), 400

    user = get_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    history = get_chat_history(user_id, limit=16)
    topics = [t["topic"] for t in get_user_topics(user_id)]
    weak = get_weak_topics(user_id)
    dashboard = get_dashboard_data(user_id)

    user_context = {
        "name": user["name"],
        "topics_studied": topics,
        "weak_topics": weak,
        "avg_score": dashboard["avg_score"],
    }

    try:
        reply = chat_with_assistant(message, history, user_context)
    except Exception:
        logger.exception("Chat generation failed for user_id=%s", user_id)
        return jsonify({"error": "The assistant is temporarily unavailable. Please try again."}), 502

    save_chat_message(user_id, "user", message)
    save_chat_message(user_id, "assistant", reply)

    return jsonify({"reply": reply})


@app.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    """Return chat history for display."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(get_chat_history(user_id, limit=50))


@app.route("/api/chat/clear", methods=["POST"])
def api_chat_clear():
    """Clear chat history for the current user."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    clear_chat_history(user_id)
    return jsonify({"ok": True})


# ─── Dashboard & History API ──────────────────────────────────────────────────

@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    """Return aggregated stats for the dashboard."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(get_dashboard_data(user_id))


@app.route("/api/history/topics", methods=["GET"])
def api_history_topics():
    """Return all topics studied by the current user."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(get_user_topics(user_id))


@app.route("/api/history/quizzes", methods=["GET"])
def api_history_quizzes():
    """Return all quiz results for the current user."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(get_user_quiz_results(user_id))


# ─── System status API ────────────────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
def api_status():
    """Check if the Gemini API is reachable and configured correctly."""
    return jsonify(check_ai_status())


# ─── Entry point (local development only — production uses Gunicorn) ─────────────

if __name__ == "__main__":
    logger.info("AI Study Assistant starting in local dev mode...")
    logger.info("Checking Gemini API status...")
    status = check_ai_status()
    logger.info(status["message"])
    logger.info("Open http://localhost:%s in your browser", Config.PORT)
    app.run(debug=Config.DEBUG, host="0.0.0.0", port=Config.PORT)
