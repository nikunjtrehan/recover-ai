# RecoverAI

Automated payment failure recovery for Razorpay merchants.

**Razorpay AI Buildathon 2026 — Track 3: Revenue Recovery**

---

## What this does

When a payment fails on Razorpay (card declined, UPI timeout, insufficient funds), this system receives the webhook, classifies the failure, picks the right recovery action, and sends a localized message to the customer — all without a human in the loop.

The entire hot-path runs in under 5 milliseconds. No LLM API call in the transaction path. The AI component runs offline, asynchronously optimizing message templates from audit logs.

## Why it's built this way

Most hackathon projects slap an LLM on every API call. That's a bad idea for payments:

- **Latency**: A GPT-4 call takes 2-8 seconds. A payment retry window is measured in milliseconds.
- **Reliability**: If OpenAI is down, your recovery pipeline is down. Merchants lose money.
- **Cost**: At scale, per-transaction LLM calls destroy unit economics.
- **Compliance**: RBI requires deterministic, auditable decision-making. "The LLM decided" is not an acceptable answer.

So the architecture splits into two paths:

**Hot path (synchronous, <5ms):**
Webhook → RandomForest classifier → Python rules engine → bounded action → localized message → Razorpay API

**Cold path (async batch, runs daily):**
SQLite audit logs → Gemini 1.5 Flash → rewritten Hinglish templates → saved to disk for next day

The classifier handles *what kind* of failure it is. The rules engine handles *what to do about it*. The LLM handles *how to say it better* — but only offline, never blocking a transaction.

## Architecture

```
Razorpay Webhook (payment.failed)
        |
        v
FastAPI Server (server.py)
        |
        v
RandomForest Classifier ──> category: transient | recoverable | terminal | suspicious
        |
        v
Rules Engine (recovery_agent.py) ──> action: retry | payment_link | paylater | escalate
        |
        v
Message Generator ──> English / Hindi / Hinglish templates
        |
        v
Razorpay SDK (test mode) ──> execute action
        |
        v
SQLite Audit Trail ──> every decision logged with reasoning
        |
        v (async, daily)
Offline Optimizer ──> Gemini reads logs, rewrites templates
```

## Setup

```bash
git clone <repo-url>
cd recover_ai

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt

copy .env.example .env
# Add your GOOGLE_API_KEY (for offline optimizer, optional)
# Add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET (test mode)

python data/generate_synthetic.py
python run_evaluation.py
streamlit run app.py
```

## Evaluation results

Run `python run_evaluation.py` to reproduce. These are measured on a held-out test set of 25 transactions, not cherry-picked.

**Classification:**

| Category    | Precision | Recall | F1    | Support |
|-------------|-----------|--------|-------|---------|
| transient   | 1.000     | 1.000  | 1.000 | 12      |
| recoverable | 1.000     | 1.000  | 1.000 | 8       |
| terminal    | 1.000     | 1.000  | 1.000 | 4       |
| suspicious  | 1.000     | 1.000  | 1.000 | 1       |

100% accuracy is because the classifier falls back to a deterministic error-code lookup table (`data/bank_error_codes.json`) when no trained model exists. This is by design — the ML model is a future upgrade path, not a requirement. The rule-based classifier is already correct for known error codes.

**Recovery pipeline:**

| Metric           | Value                    |
|------------------|--------------------------|
| Recovery rate    | 59.9% (simulated)        |
| Amount recovered | Rs 52,816 / Rs 88,192    |
| Escalation rate  | 20.0%                    |
| Exceptions       | 6 / 25 unrecoverable     |

Recovery outcomes are simulated because Razorpay test mode cannot execute real retries. Classification and strategy selection are fully real. The 6 exceptions are honest failures — terminal card declines and insufficient funds cases where no automated action would help.

## Safety and compliance

- **Bounded actions**: The agent can only execute actions from `config.ALLOWED_ACTIONS`. It cannot hallucinate a refund, create a discount, or issue credit.
- **Escalation chain**: retry → payment link → PayLater → human. Levels cannot be skipped.
- **Stopping rules**: Max 3 retries, 4-hour cooldown between attempts, max 3 customer touchpoints.
- **Suspicious payments**: Always escalated to human review immediately. No automated retry.
- **Audit trail**: Every decision is written to SQLite with: payment_id, action, reasoning, confidence score, timestamp, outcome.
- **No micro-credit**: Uses Razorpay PayLater (NBFC-compliant) instead of issuing unauthorized credit.

## Message samples

| Failure          | Language  | Message |
|------------------|-----------|---------|
| Card declined    | Hinglish  | "Hi Rahul! Aapka Rs 1,499 ka payment process nahi ho paya. Koi baat nahi — is link se UPI se try karein: [link]" |
| Card expired     | Hinglish  | "Priya ji, aapka card expire ho gaya hai. Naya card add karein ya UPI use karein: [link]" |
| Bank timeout     | Hindi     | "Namaste Amit! Bank timeout ki wajah se payment ruk gaya. Hum automatically retry kar rahe hain." |

## Project structure

```
recover_ai/
  app.py                     Streamlit dashboard
  server.py                  FastAPI webhook server
  config.py                  Settings, allowed actions, failure categories
  run_evaluation.py          Evaluation on held-out test set
  requirements.txt
  .env.example

  src/
    classifier.py            RandomForest failure classifier
    recovery_agent.py        Strategy engine (rules + optional LLM)
    message_generator.py     Localized message templates
    retry_engine.py          Executes recovery actions via Razorpay SDK
    escalation.py            Escalation chain management
    audit.py                 SQLite audit trail
    razorpay_client.py       Razorpay SDK wrapper (test mode)

  scripts/
    offline_optimizer.py     Async LLM template optimization (Gemini)

  data/
    bank_error_codes.json    Error code → category mapping
    generate_synthetic.py    Test data generator
    synthetic_payments.json  Training data
    synthetic_test_set.json  Held-out evaluation data
```

## Tech stack

| Component   | Choice               | Why                                              |
|-------------|----------------------|--------------------------------------------------|
| Server      | FastAPI + Uvicorn    | Async, fast, native Pydantic validation          |
| Classifier  | scikit-learn (RF)    | Sub-millisecond inference, no GPU needed          |
| LLM         | Google Gemini (free) | Offline only, free tier sufficient for batch work |
| Payments    | Razorpay Python SDK  | Official SDK, test mode support                   |
| Audit       | SQLite               | Zero config, single file, portable                |
| Dashboard   | Streamlit + Plotly   | Rapid prototyping, built-in charting              |

## Limitations (honest)

- Recovery outcomes are simulated. Razorpay test mode does not support real payment retries.
- The ML classifier currently falls back to a lookup table. A trained model would improve on edge cases with ambiguous error codes.
- SQLite will not scale past ~100 concurrent webhook writes. Production would need PostgreSQL with async writes.
- The offline optimizer requires a Gemini API key. Without it, the system uses static templates (which still work).
- Single-process server. Production would need worker processes behind a load balancer.

## License

MIT
