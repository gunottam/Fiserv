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
├── app.py                      # FastAPI entrypoint + CORS + lifespan (Telegram bot)
├── schemas/
│   └── predict.py              # PredictRequest / PredictResponse (shared)
├── routes/
│   ├── predict.py              # POST /predict (thin; delegates to pipeline)
│   ├── demand.py               # GET /demand-series for the chart baseline
│   └── chat.py                 # POST /chat, grounded reasoning over a decision
├── services/
│   ├── pipeline.py             # core /predict orchestration (testable entry)
│   ├── inference.py            # model.pkl loader + dummy fallback predictor
│   ├── context_engine.py       # applies +20% boosts (peak / weekend / history)
│   ├── restock.py              # restock qty, urgency, coverage, stockout risk
│   ├── explain.py              # one-shot Groq explanation + rule fallback
│   ├── chat.py                 # multi-turn Groq chat + rule fallback
│   ├── telegram.py             # HIGH/MEDIUM push alerts (optional, dedup + mute)
│   └── telegram_bot.py         # long-poll listener: /help, /status, /alerts, …
├── utils/
│   └── preprocessing.py        # day-of-week + item_id encoding, feature prep
├── scripts/
│   └── train_model.py          # multi-algo benchmark → saves winner to models/
├── requirements.txt
├── .env.example
└── README.md
```

Artifacts written into the repo-root `models/` folder by the training script:

* `model.pkl`               — joblib-pickled winning sklearn/xgboost/lightgbm regressor.
* `item_stats.json`         — per-item integer encoding, historical stockout rate,
                              mean velocity, winner metrics, and feature order.
* `comparison_report.json`  — full side-by-side ranking for every candidate
                              algorithm evaluated on the chronological hold-out.

## Model benchmark

`scripts/train_model.py` trains five candidates on the historical CSV, scores
each on a chronological hold-out (no shuffle — trailing 20% is held out), and
saves the best-MAE winner as `models/model.pkl`. Honest feature set only: no
`is_stock_out` leakage, no rolling lag features the live request wouldn't have.

Latest run on `dataset/bakery_inventory.csv` (75,600 rows, 10 SKUs, 18 mo):

| rank | candidate         | test MAE | test RMSE | test R² | fit  | pred |
|-----:|-------------------|---------:|----------:|--------:|-----:|-----:|
|    1 | gradient_boost    |    1.250 |     1.640 |  0.9487 |  7.4s| 0.04s|
|    2 | xgboost           |    1.256 |     1.646 |  0.9483 |  0.7s| 0.01s|
|    3 | lightgbm          |    1.258 |     1.649 |  0.9481 |  4.9s| 0.04s|
|    4 | random_forest     |    1.282 |     1.689 |  0.9456 |  0.8s| 0.05s|
|    5 | ridge             |    2.105 |     2.663 |  0.8647 |  0.0s| 0.00s|

Naive-mean MAE baseline is 5.68 units/hr, so the winner is **78% below** the
no-skill baseline. GBDTs cluster within 0.03 u/hr — for production the XGBoost
model is arguably preferable (10× faster fit, ~identical accuracy); re-run with
`python -m scripts.train_model --only xgboost` to force it.

## Quick start

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# macOS only: xgboost + lightgbm need `brew install libomp`.

# Benchmark all five algorithms on dataset/bakery_inventory.csv and
# save the winner → models/model.pkl + models/item_stats.json + comparison_report.json
python -m scripts.train_model

# Restrict to a subset:
#   python -m scripts.train_model --only xgboost,lightgbm
# Use a different CSV:
#   python -m scripts.train_model --dataset ../dataset/dataset.csv

cp .env.example .env
# edit .env, paste your GROQ_API_KEY (optional — backend still works without it)
uvicorn app:app --reload --port 8000
```

The `/` health endpoint reports `model_loaded`, `item_stats_loaded`,
`dataset_available`, `groq_configured`, `telegram_configured`, and
`telegram_bot_running` (true when the interactive listener is active) so you
can verify everything wired up. A fresh install without training still works —
inference.py falls back to a per-item heuristic and
`historical_stockout_rate` defaults to 0.

## Telegram notifications (optional)

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`, every
`HIGH` or `MEDIUM` `/predict` response triggers a short Markdown alert to
Telegram. `LOW` urgency is a silent no-op. The call runs via FastAPI's
`BackgroundTasks` so it fires *after* the HTTP response — a slow or failing
Telegram API can never block or error the client. Missing env vars, timeouts,
and non-2xx responses are logged and swallowed.

**Dedup:** repeat alerts for the same `(item_id, urgency)` are suppressed for
`TELEGRAM_DEDUP_SECONDS` (default 300) so dashboard refreshes do not flood the
chat or hit Telegram rate limits.

**Interactive bot:** on startup, the backend also runs a long-polling
listener (`services/telegram_bot.py`) in the same process as uvicorn. Open
your chat with the bot and use the built-in `/` menu, or type:

| Command | What it does |
|--------|----------------|
| `/start` | Short intro |
| `/help` | All commands |
| `/status` | Counts of HIGH / MEDIUM / LOW from recent `/predict` decisions |
| `/alerts` | Top active HIGH and MEDIUM lines (from the same in-memory cache) |
| `/mute [minutes]` | Pause push alerts (default 15 min, max 24 h) |
| `/unmute` | Resume push alerts |
| `/ping` | Quick round-trip; replies are local (tens of ms, no LLM) |

Only messages from the configured `TELEGRAM_CHAT_ID` are accepted; other chats
are ignored. Command replies use Markdown and never call Groq, so they feel
instant.

Setup:

1. Create a bot with [@BotFather](https://t.me/BotFather) to get the token.
2. Start a chat with your bot (or add it to a group), then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id`.
3. Set both values in `backend/.env`. Leave either blank to disable push
   alerts; the command listener also stays off if the token is missing.
4. Restart `uvicorn` after changing `.env` so the bot picks up new values.

Sample push alert:

```
🚨 *HIGH URGENCY ALERT*

📦 Item: Croissants
📍 Store: IND-01
📊 Stock: 7 units

⚡ Demand: 22.0 units/hr
📉 Coverage: 0.8 hours

📦 *Restock Now: +30 units*

🧠 _Saturday morning peak with rising demand and past stockouts_
```

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
