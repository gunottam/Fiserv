# Contextual Inventory Intelligence

A small full-stack system that turns **live inventory snapshots** into **restock decisions**: urgency, recommended order size, velocity signals, and short explanations. It includes a **Next.js** operator dashboard, a **FastAPI** decision API, **ML training** on historical bakery-style data, and optional **Telegram** alerts plus an interactive bot.

## Repository layout

| Path | Role |
|------|------|
| [`frontend/`](frontend/) | Next.js 16 + TypeScript + Tailwind v4 + shadcn/ui — multi-item alert dashboard, charts, chat drawer |
| [`backend/`](backend/) | FastAPI — `POST /predict`, `POST /chat`, `GET /demand-series`, health, Telegram integration |
| [`dataset/`](dataset/) | CSVs (e.g. large `bakery_inventory.csv` for training and demand series) |
| [`models/`](models/) | Trained artifacts: `model.pkl`, `item_stats.json`, reports (produced by training, not always committed) |
| [`models/train_model.py`](models/train_model.py) | Legacy XGBoost script (reference only) |

**Canonical training** lives under the backend and writes into `models/`:

```bash
cd backend && source .venv/bin/activate
python -m scripts.train_model
```

See [`backend/README.md`](backend/README.md) for the full pipeline, benchmark table, env vars, and Telegram behavior.

## Prerequisites

- **Python 3.11+** (recommended) and a virtualenv for `backend/`
- **Node.js 20+** and your preferred package manager for `frontend/` (e.g. `pnpm`, `npm`)
- Optional: **Groq API key** for LLM explanations and chat (the API still works with rule-based fallbacks)
- Optional: **Telegram** bot token + chat id for push alerts and `/help`, `/status`, etc.

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: GROQ_API_KEY (optional), paths, optional TELEGRAM_*
uvicorn app:app --reload --port 8000
```

- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/](http://127.0.0.1:8000/) — reports model/dataset/Groq/Telegram status and whether the bot listener is running

### 2. Frontend

```bash
cd frontend
pnpm install   # or npm install
# Optional: create .env.local with NEXT_PUBLIC_API_BASE_URL if the API is not http://localhost:8000
pnpm dev       # or npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The UI calls the backend for predictions and demand data; ensure CORS in `backend/.env` includes your frontend origin (`CORS_ORIGINS`).

## Architecture (short)

1. **HTTP layer** — FastAPI routes validate requests and schedule side effects (e.g. Telegram `BackgroundTasks`).
2. **Decision pipeline** — [`backend/services/pipeline.py`](backend/services/pipeline.py) orchestrates preprocessing, model inference, context adjustment, restock/urgency math, and explanation generation. This keeps [`backend/routes/predict.py`](backend/routes/predict.py) thin and makes the flow easier to test or reuse.
3. **Inference** — Loads `models/model.pkl` when present; otherwise uses a heuristic predictor.
4. **Explanations** — Groq when configured; deterministic copy otherwise.
5. **Telegram** — Push notifications for HIGH/MEDIUM; long-polling command bot for operator commands (see backend README).

## Environment variables

Backend examples are in [`backend/.env.example`](backend/.env.example). Do **not** commit real API keys or tokens; use a local `.env` only.

## Contributing / development

- Backend: run from the `backend/` directory so imports (`app`, `services`, `schemas`) resolve.
- After changing types or API contracts, run `pnpm typecheck` in `frontend/` and fix any `lib/api.ts` / `lib/types.ts` drift.
- For a production-style run: `pnpm build && pnpm start` (frontend) and `uvicorn app:app --host 0.0.0.0 --port 8000` (backend) with a reverse proxy and HTTPS in front.

## License

This project is provided as-is for demonstration and development. Add a `LICENSE` file if you need explicit terms for redistribution.
