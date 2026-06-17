# 🎓 AI Study Assistant

A full-stack AI-powered study companion: chat about anything you're learning, generate explanations/notes/quizzes for any topic, and track your progress over time. Powered by **Google's Gemini API** (free tier) and deployable to **Render** in minutes.

**Stack:** Flask · SQLite · Google Gemini API · Gunicorn · vanilla JS/HTML/CSS — no frontend build step, no paid services required.

---

## Features

- **Chatbot** — ask study questions, get answers from Gemini, with memory of past topics and weak areas.
- **Study workflow** — type a topic and get: a plain-language explanation → structured study notes → a 5-question quiz → instant grading with feedback → a personalized "what to study next" recommendation.
- **Memory system** — name, studied topics, quiz scores, and weak topics are stored in SQLite and recalled in every conversation.
- **Dashboard** — topics studied, quiz attempts, average/best score, a score trend chart, and weak areas.
- **History** — a full log of every topic studied and every quiz taken, with expandable detail.
- **Multiple profiles** — no password system; pick a name and your data persists between sessions.
- **Production-ready backend** — structured logging, environment-based config, retry-with-backoff on AI calls, a `/health` endpoint for uptime monitoring, and graceful error handling throughout (a failed AI call returns a clean JSON error, never a stack trace).

---

## Architecture

```
Browser (vanilla JS) ── HTTP ──> Flask routes (app.py)
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                                    │
              database.py                          chatbot.py
              (SQLite, WAL mode)                (Google Gemini API)
```

- **`app.py`** — all Flask routes (pages + JSON API), request validation, error handling, and the `/health` endpoint. No business logic lives here beyond orchestration.
- **`database.py`** — every SQL statement in the app lives in this one file. Tables are created automatically on first run.
- **`chatbot.py`** — the only file that talks to Gemini. Wraps the `google-genai` SDK with retry/backoff, JSON-mode quiz generation, and a status check used for monitoring.
- **`config.py`** — every environment variable the app reads is declared in one place, with defaults and startup validation warnings.

---

## Tech stack

| Layer       | Technology                              |
|-------------|-------------------------------------------|
| Frontend    | HTML, CSS, vanilla JavaScript               |
| Backend     | Python 3 + Flask                            |
| WSGI server | Gunicorn (production) / Flask dev server (local) |
| Database    | SQLite, WAL mode (auto-created on first run) |
| AI model    | Google Gemini API — `gemini-2.5-flash` (free tier) |
| Deployment  | Render (Blueprint via `render.yaml`, or manual Web Service) |

---

## Project structure

```
ai-study-assistant/
├── app.py                  # Flask routes, error handling, /health endpoint
├── config.py                # Centralized environment-variable configuration
├── database.py               # SQLite schema + all DB operations
├── chatbot.py                  # Google Gemini API integration
├── schema.sql                   # Human-readable copy of the DB schema (reference only)
├── requirements.txt               # Python dependencies
├── render.yaml                      # Render Blueprint (one-click deploy config)
├── Procfile                          # Process declaration (gunicorn start command)
├── .env.example                       # Template for required environment variables
├── .gitignore                          # Excludes .env, *.db, __pycache__, venv, etc.
├── templates/
│   ├── base.html                        # Shared layout (sidebar, mobile header)
│   ├── index.html                        # Landing page — create/select a profile
│   ├── chat.html                          # Chat interface
│   ├── study.html                          # Study workflow (explain → notes → quiz → results)
│   ├── dashboard.html                       # Progress dashboard
│   └── history.html                          # Full study/quiz history
└── static/
    ├── css/style.css                          # All styling
    └── js/script.js                            # Shared JS (sidebar, status indicator, logout)
```

---

## Local setup

### 1. Get a free Gemini API key

Visit [Google AI Studio](https://aistudio.google.com/app/apikey) and create a free API key. No credit card is required for the free tier (rate-limited, but generous enough for a project like this).

### 2. Install dependencies

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
GEMINI_API_KEY=your-real-key-here
SECRET_KEY=generate-one-below
```

Generate a real `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Run the app

```bash
python app.py
```

```
2026-06-17 10:00:00 [INFO] study_assistant: AI Study Assistant starting in local dev mode...
2026-06-17 10:00:00 [INFO] study_assistant: Checking Gemini API status...
2026-06-17 10:00:01 [INFO] study_assistant: Gemini API connected ✅ (gemini-2.5-flash)
2026-06-17 10:00:01 [INFO] study_assistant: Open http://localhost:5000 in your browser
```

Open **http://localhost:5000**. The SQLite database (`study_assistant.db`) and all tables are created automatically on first request — no manual migration step.

### Running with Gunicorn locally (optional, mirrors production)

```bash
gunicorn app:app --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120
```

---

## Deploying to Render

### Option A — One-click Blueprint (recommended)

1. Push this repository to GitHub (make sure `.env` is **not** committed — `.gitignore` already excludes it).
2. In the Render dashboard, click **New +** → **Blueprint**.
3. Connect your repository. Render detects `render.yaml` automatically and pre-fills the service configuration.
4. When prompted, set the **`GEMINI_API_KEY`** environment variable to your real key (it's marked `sync: false` in `render.yaml`, so Render asks you for it rather than committing it to source control). `SECRET_KEY` is auto-generated by Render — you don't need to provide it.
5. Click **Apply**. Render installs dependencies (`pip install -r requirements.txt`) and starts the app with Gunicorn.
6. Once the deploy finishes, your app is live at `https://<your-service-name>.onrender.com`.

### Option B — Manual Web Service

1. In the Render dashboard: **New +** → **Web Service** → connect your repo.
2. **Runtime:** Python 3
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
5. **Health Check Path:** `/health`
6. Under **Environment**, add:
   - `GEMINI_API_KEY` — your real key
   - `SECRET_KEY` — output of `python -c "import secrets; print(secrets.token_hex(32))"`
   - `SESSION_COOKIE_SECURE` = `true`
   - `FLASK_DEBUG` = `false`
7. Click **Create Web Service**.

### A note on data persistence

Render's free-tier filesystem is **ephemeral** — it's wiped on every redeploy or restart. That means the SQLite file (and everyone's study history) resets each time you push a new commit. This is normal and expected for a free-tier demo/portfolio deployment.

If you want data to survive redeploys, attach a [Render Disk](https://render.com/docs/disks) (requires a paid plan) and set `DATABASE_PATH` to a path inside that mount — `render.yaml` includes a commented-out example of exactly this.

---

## API overview

All endpoints except the page routes and `/health` return JSON and require an active session (created via `/api/users` or `/api/users/select`).

| Method | Path                        | Purpose                                  |
|--------|-----------------------------|--------------------------------------------|
| GET    | `/health`                    | Liveness/readiness probe for deployment monitoring |
| GET    | `/api/status`                  | Checks whether the Gemini API is reachable and configured |
| GET/POST | `/api/users`                  | List profiles / create a new profile |
| POST   | `/api/users/select`              | Switch to an existing profile |
| POST   | `/api/users/logout`               | Clear the session |
| POST   | `/api/study/start`                 | Generate explanation + notes for a topic, save to DB |
| POST   | `/api/study/quiz/generate`          | Generate 5 quiz questions for a topic |
| POST   | `/api/study/quiz/submit`             | Grade a quiz, save the result, flag weak topics |
| POST   | `/api/chat`                           | Send a chat message, get an AI reply |
| GET    | `/api/dashboard`                       | Aggregated stats for the dashboard |
| GET    | `/api/history/topics` / `/quizzes`      | Full study/quiz history |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Sidebar status dot is red / "Gemini API unavailable" | Confirm `GEMINI_API_KEY` is set and valid. Check application logs for the exact error. |
| `/health` returns 503 | The SQLite database isn't reachable — check `DATABASE_PATH` and filesystem permissions. |
| Quiz generation occasionally fails | Gemini occasionally returns malformed JSON; the app already retries automatically and validates structure before saving — just click **Take the quiz** again if it fails. |
| 429 / rate-limit errors in logs | You've hit the Gemini free-tier rate limit. The app retries with backoff automatically; for heavier use, request a quota increase or enable billing in Google AI Studio. |
| Render service "spins down" and is slow on first request | Expected on Render's free tier — services sleep after 15 minutes of inactivity and take a few seconds to wake up. |
| Local dev: `ModuleNotFoundError: google.genai` | Run `pip install -r requirements.txt` — the dependency is `google-genai`, not the older deprecated `google-generativeai`. |

---

## Security notes

- API keys and the Flask secret key are read exclusively from environment variables — never hardcoded, never committed (`.gitignore` excludes `.env`).
- Session cookies are marked `HttpOnly` and `SameSite=Lax` always, and `Secure` when `SESSION_COOKIE_SECURE=true` (set this in production, since Render serves over HTTPS).
- All user-facing routes validate and bound-check input (name length, topic length, message length, answer-count matching question-count) before touching the database or calling the AI.
- A global Flask error handler ensures unhandled exceptions never leak stack traces to the client — they're logged server-side and returned as a generic JSON error instead.

---

## License

This project is provided as-is for educational and portfolio purposes.
