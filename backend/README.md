# Contextual Inventory Intelligence — Backend

FastAPI service that turns a live inventory snapshot into a restock decision
backed by a short natural-language rationale (Groq).

## Pipeline

```
Request ──► preprocess ──► predict velocity ──► context engine ──► restock + urgency ──► explanation ──► Response
                          (model or dummy)     (+20% per rule)    (peak → cover 5h)     (Groq or rules)
```

## Project layout

```
backend/
├── app.py                      # FastAPI entrypoint + CORS
├── routes/
│   ├── predict.py              # POST /predict, orchestrates the pipeline
│   └── chat.py                 # POST /chat, grounded reasoning over a decision
├── services/
│   ├── inference.py            # model.pkl loader + dummy fallback predictor
│   ├── context_engine.py       # applies +20% boosts (peak / weekend / history)
│   ├── restock.py              # restock qty, urgency, coverage, stockout risk
│   ├── explain.py              # one-shot Groq explanation + rule fallback
│   └── chat.py                 # multi-turn Groq chat + rule fallback
├── utils/
│   └── preprocessing.py        # day-of-week + item_id encoding, feature prep
├── scripts/
│   └── train_model.py          # trains on dataset/dataset.csv, emits artifacts
├── requirements.txt
├── .env.example
└── README.md
```

Artifacts written into the repo-root `models/` folder by the training script:

* `model.pkl`         — joblib-pickled sklearn `GradientBoostingRegressor`.
* `item_stats.json`   — per-item integer encoding, historical stockout rate,
                        mean velocity, training metrics, and feature order.

## Quick start

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Train the model on dataset/dataset.csv → models/model.pkl + models/item_stats.json
python -m scripts.train_model

cp .env.example .env
# edit .env, paste your GROQ_API_KEY (optional — backend still works without it)
uvicorn app:app --reload --port 8000
```

The `/` health endpoint reports `model_loaded`, `item_stats_loaded`, and
`groq_configured` so you can verify everything wired up. A fresh install
without training still works — inference.py falls back to a per-item
heuristic and `historical_stockout_rate` defaults to 0.

Health check: <http://localhost:8000/> · Docs: <http://localhost:8000/docs>

## Example call

```bash
curl -X POST http://localhost:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{
    "item_id": "BK-01",
    "item_name": "Croissants",
    "current_stock": 7,
    "threshold": 10,
    "day_of_week": "Saturday",
    "hour": 9,
    "is_peak_hour": true
  }'
```

Response (shape):

```json
{
  "item_id": "BK-01",
  "item_name": "Croissants",
  "urgency": "HIGH",
  "restock": 130,
  "predicted_velocity": 19.5,
  "adjusted_velocity": 28.08,
  "coverage_hours": 0.25,
  "stockout_risk": 87.5,
  "current_stock": 7,
  "threshold": 10,
  "context_factors": ["Peak hour", "Weekend"],
  "day_of_week": "Saturday",
  "hour": 9,
  "is_peak_hour": true,
  "historical_stockout_rate": 0.124,
  "explanation": "High urgency: Saturday morning peak …"
}
```

## POST /chat — grounded reasoning

After a `/predict` call, hand the full response back as ``context`` to let the
operator interrogate the decision. The server is **stateless** — the UI owns
the conversation history.

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "context": <the /predict response object>,
    "message": "Why HIGH urgency? What if it werent peak hour?",
    "history": [
      {"role": "user",      "content": "Why are we restocking so many?"},
      {"role": "assistant", "content": "Peak Saturday + weekend + stockout history…"}
    ]
  }'
```

Response:

```json
{
  "reply": "Predicted velocity is 13.27 u/hr. Three boosts fire (peak, weekend, history) → adjusted 22.93 u/hr. Coverage = 5 / 22.93 = 0.22h, below the 1.0h HIGH threshold, so we recommend 5h of peak coverage → 110 units.",
  "groq_used": true
}
```

When `GROQ_API_KEY` is missing or the call fails, `groq_used` is `false` and
`reply` is a deterministic rule-based summary so the UI never shows an error.

## Plugging into the frontend

CORS allows `http://localhost:3000` by default. Typical flow from the Next.js
app:

```ts
// 1. Get the decision.
const predictRes = await fetch("http://localhost:8000/predict", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
})
const decision = await predictRes.json()

// 2. When the operator asks a question, forward the decision as context.
const chatRes = await fetch("http://localhost:8000/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    context: decision,
    message: userInput,
    history,          // [{role, content}, …] maintained client-side
  }),
})
const { reply } = await chatRes.json()
```

## Notes

- **No model file?** Drop a trained `joblib`-pickled sklearn regressor at
  `../models/model.pkl` (or override with `MODEL_PATH`). Without it the service
  uses a small heuristic (day-of-week × hour multipliers) so the API is always
  callable.
- **No Groq key?** `services/explain.py` returns a well-formatted rule-based
  explanation instead of failing.
- **Extending**: every stage is a plain function — easy to swap in a real model,
  a feature store, or a different LLM provider without touching the route.
