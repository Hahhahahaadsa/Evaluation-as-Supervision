# How to Run

Multi-Agent System for Restaurant Review Analysis. There are three ways to run
it, from lightest to full:

1. **CLI** - run the agent pipeline on one restaurant, no web server.
2. **Local web app** - FastAPI backend + React frontend on your machine.
3. **On a server** - one public URL a user opens in a browser (the "ideal" demo).

The LLM provider is chosen entirely by environment variables (cloud Gemini or a
local Ollama model); see [docs/LOCAL_LLM.md](docs/LOCAL_LLM.md). The provider and
model actually used are recorded in every run's `_summary.json -> run_config`.

---

## Prerequisites

- **Python 3.10+** (backend)
- **Node.js 18+** and npm (frontend)
- An **LLM provider**, one of:
  - *Cloud:* a Google AI Studio (Gemini) API key, or
  - *Local:* [Ollama](https://ollama.com/download) with a pulled model
    (`ollama pull llama3.1`) - no API key needed.
- The **Yelp dataset** files under `backend/data/raw/` (git-ignored, not shipped)
  for any real report. The in-memory tests and eval fixture do not need them.

---

## 1. CLI (fastest check)

```bash
cd backend

python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Choose a provider profile:
cp .env.example .env              # cloud: then set OPENAI_API_KEY=<your Gemini key>
# cp .env.local.example .env      # local: needs `ollama serve` + a pulled model

python run_pipeline.py --name "McDonald's" --pick 1 --dump-stages out/
cat out/_summary.json             # run_config confirms which provider ran
```

Useful flags: `--pick N` (auto-select the Nth fuzzy match), `--sample-size N`
(1-100), `--json` (raw report JSON), `--dump-stages DIR` (write each agent's
output for evaluation).

---

## 2. Local web app (two terminals)

**Terminal A - backend** (from `backend/`, venv active, `.env` set as above):

```bash
uvicorn app.main:app --reload --port 8000
```

The API serves on `http://localhost:8000` (`/health`,
`/api/businesses/search`, `/api/reports`, and the SSE stream
`/api/reports/stream`).

**Terminal B - frontend:**

```bash
cd frontend
npm install
npm run dev                       # Vite dev server on http://localhost:5173
```

Open **http://localhost:5173**. The frontend calls the backend at
`http://localhost:8000` by default (`VITE_API_BASE_URL`), so no extra config is
needed when both run locally.

For the **local-LLM** path, start Ollama first (`ollama serve`, model pulled)
and use the `.env.local.example` profile. Keep `MAX_REVIEW_SAMPLE` modest
(e.g. 20-50) since a small local model on CPU is slow.

### Speed: build the SQLite index

Without an index each report scans the ~5.34 GB raw dataset. Build it once:

```bash
cd backend
python scripts/build_db.py
```

---

## 3. On a server (browser access - the ideal demo)

Goal: a single public HTTPS URL. The clean approach is **single-origin** - build
the frontend as static files that call the backend on the same origin, so there
is no cross-origin or base-URL juggling.

**Build the frontend for same-origin:**

```bash
cd frontend
VITE_API_BASE_URL="" npm run build      # outputs frontend/dist/, calls /api/... relatively
```

**Run the backend on all interfaces:**

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then pick a hosting style:

- **Managed platform (simplest):** deploy the backend to Render / Railway / Fly /
  a VM with start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT` and
  the provider env vars set. Host `frontend/dist/` on Vercel/Netlify built with
  `VITE_API_BASE_URL=<backend public URL>`, **or** serve `dist/` from the backend
  itself (a small `StaticFiles` mount in `app/main.py`) so there is only one URL.
- **Your own VM:** put **nginx** or **Caddy** in front for HTTPS, reverse-proxying
  to uvicorn.
- **Quick demo tunnel:** run locally and expose it with `cloudflared` or `ngrok`.
  If you tunnel, build the frontend against the public backend URL - a remote
  browser cannot reach your `localhost:8000`.

### Server gotchas specific to this project

- **SSE / live progress:** the pipeline streams via `EventSource`. Your reverse
  proxy must disable response buffering (nginx: `proxy_buffering off;`) or the
  progress stream stalls.
- **Dataset:** the ~5.34 GB Yelp files are git-ignored, so a fresh host has none.
  Build the SQLite index and upload it (or the dataset), or reports cannot run.
- **LLM choice:** a hosted box naturally demos the **cloud (Gemini)** profile. The
  **local (Ollama)** profile only works on the server if Ollama also runs on that
  host - so the local-LLM demo is usually shown on a laptop while the hosted URL
  shows the cloud path.
- **Security:** the API currently has wildcard CORS, no auth, no rate limits, and
  streams raw error details (see [PROJECT_AUDIT.md](PROJECT_AUDIT.md)). Acceptable
  for a supervised demo; do not leave a public URL up unattended.

---

## Verifying a run

```bash
cd backend
python -m pytest                                   # tests (live tests run only with a key)
python -m eval.tier1_checks eval/fixtures/sample_dump   # deterministic eval on the fixture
cat out/_summary.json                              # run_config = provider/model actually used
```

See [docs/RUN_TESTS.md](docs/RUN_TESTS.md) for the full test/eval matrix and
[docs/LOCAL_LLM.md](docs/LOCAL_LLM.md) for the local-model walkthrough.
