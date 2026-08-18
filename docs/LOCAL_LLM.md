# Running the system on a local LLM (Ollama)

Option D requires the agents to run against **both** a locally-deployed LLM and a
cloud LLM. The system is provider-agnostic: every agent and the orchestrator
talk to an **OpenAI-compatible** endpoint selected purely by environment
variables (resolved centrally in [`app/core/llm_config.py`](../backend/app/core/llm_config.py)).
Switching between local and cloud is therefore a `.env` change, not a code
change, and the provider/model actually used is recorded in every evaluation
dump (`_summary.json -> run_config`).

| Profile | Endpoint | Example models | Env file |
|---------|----------|----------------|----------|
| **Cloud** (default) | Gemini OpenAI-compat | `gemini-2.5-flash` / `gemini-3.5-flash` | `backend/.env.example` |
| **Local** | Ollama on `localhost:11434` | `llama3.1` / `llama3.1` | `backend/.env.local.example` |

## 1. Install Ollama and pull a model

1. Install Ollama for your OS: https://ollama.com/download
2. Pull a model (any instruction-tuned chat model works; `llama3.1` 8B is a good
   laptop default, `qwen2.5` and `mistral` also work):

   ```bash
   ollama pull llama3.1
   ```
3. Ollama automatically serves an OpenAI-compatible API at
   `http://localhost:11434/v1`. Confirm it is up:

   ```bash
   curl http://localhost:11434/v1/models
   ```

## 2. Point the app at the local runtime

```bash
cp backend/.env.local.example backend/.env
```

That profile sets:

```dotenv
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama          # any non-empty value; Ollama ignores it
OPENAI_MODEL=llama3.1
OPENAI_FALLBACK_MODEL=llama3.1
```

You do **not** need a real API key: `llm_config` injects a placeholder for any
local endpoint (`localhost`, `127.0.0.1`, `:11434`, ...), so an unset
`OPENAI_API_KEY` still works. The guards that previously required
`OPENAI_API_KEY` now accept a local endpoint instead.

## 3. Run the pipeline locally

```bash
cd backend
python run_pipeline.py --name "McDonald's" --pick 1 --dump-stages out/
```

The run makes real calls to your local model (no network, no cost). Because the
whole graph runs on the same endpoint, the orchestrator recovery call and all
four agents (analysis, reasoning, strategy, report) use the local model too.

## 4. Verify which provider actually ran

Every dump records provenance, so local and cloud runs are unambiguous:

```bash
cat out/_summary.json
```

```json
"run_config": {
  "provider": "ollama-local (openai-compatible)",
  "base_url": "http://localhost:11434/v1",
  "primary_model": "llama3.1",
  "fallback_model": "llama3.1"
}
```

A cloud run shows `"provider": "google-gemini (openai-compatible)"` with the
Gemini models. This is exactly what the evaluation write-up cites when comparing
local vs cloud output quality (Tier 2 accuracy / Tier 3 rubric scores).

## 5. Switch back to cloud

```bash
cp backend/.env.example backend/.env   # then paste your Gemini key into OPENAI_API_KEY
```

## Notes and troubleshooting

- **JSON mode.** The agents request `response_format={"type":"json_object"}`.
  Recent Ollama builds honour this on the `/v1` endpoint. If your model ignores
  it and returns prose, upgrade Ollama, or pick a model that follows JSON
  instructions well (`llama3.1`, `qwen2.5`); the agents' two self-correction
  retries also recover most malformed outputs.
- **Speed.** An 8B model on CPU is slow. Keep `MAX_REVIEW_SAMPLE` modest (e.g.
  20-50) for local demos; the cap is validated 1-100.
- **Fallback.** For a real dual-model local setup, pull a second model and set
  `OPENAI_FALLBACK_MODEL` to it (e.g. `qwen2.5:3b`) so the fallback path is
  genuinely exercised.
- **Frontend/server demo.** The provider choice is backend-only; the FastAPI
  server and React UI are unchanged. Hosting the server for browser access (the
  "run on a server" item) is orthogonal and typically demoed with the cloud
  profile.
