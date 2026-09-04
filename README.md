<div align="center">

# RecoverAI

**Automated payment failure recovery for Razorpay merchants**

*Razorpay AI Buildathon 2026 — Track 3: Revenue Recovery*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests 47/47](https://img.shields.io/badge/Tests-47%2F47_passing-2ea44f)](tests/test_core.py)
[![License MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Razorpay SDK](https://img.shields.io/badge/Razorpay-SDK_v1.4-072654?logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjxyZWN0IHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgZmlsbD0ibm9uZSIvPjx0ZXh0IHg9IjQiIHk9IjE4IiBmb250LXNpemU9IjE2IiBmaWxsPSJ3aGl0ZSI+Ujwv dGV4dD48L3N2Zz4=)](https://razorpay.com)
[![Gemini](https://img.shields.io/badge/LLM-Gemini_3.5_Flash-4285F4?logo=google&logoColor=white)](https://ai.google.dev)

[Quick Start](#setup) · [Architecture](#architecture) · [Evaluation](#evaluation-results) · [Website](https://nikunjtrehan.github.io/recover-ai/)

</div>

---

### The Problem

When a payment fails — card declined, UPI timeout, insufficient funds — merchants lose that sale. Current solutions retry blindly (card networks block you) or send generic English emails (single-digit open rates in India).

### The Insight

**Not all failures are the same.** A UPI timeout (retry in 5 min) is fundamentally different from a stolen card flag (never retry, escalate immediately). Different failures need different recovery strategies, in the customer's language.

### The Architecture Decision

No LLM in the transaction path. The hot path is pure Python, sub-5ms. The AI runs offline — reading yesterday's audit logs, rewriting tomorrow's Hinglish templates.

```
                         ┌──────────────────────────────────┐
                         │     HOT PATH  (<5ms, no LLM)     │
                         └──────────────────────────────────┘

    Razorpay Webhook ──→ Classifier ──→ Rules Engine ──→ Message Gen ──→ Razorpay SDK
    (payment.failed)     17 error       4 categories     English /      create_order()
                         codes          6 bounded        Hindi /        create_payment_link()
                         mapped         actions          Hinglish       escalate_to_human()
                              │                                              │
                              └──────────── SQLite Audit Trail ──────────────┘
                                           (every decision logged)
                                                    │
                         ┌──────────────────────────────────┐
                         │    COLD PATH  (daily, async)      │
                         └──────────────────────────────────┘
                                                    │
                              Gemini 3.5 Flash reads audit logs
                              Rewrites Hinglish templates with
                              behavioral economics nudges
                              Saves to optimized_templates.json
```

---

## Setup

```bash
git clone https://github.com/nikunjtrehan/recover-ai.git
cd recover-ai

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt

copy .env.example .env
# Add your GOOGLE_API_KEY (for offline optimizer, optional)

# Generate test data and run evaluation
python data/generate_synthetic.py
python run_evaluation.py

# Run tests
python -m pytest tests/ -v

# Launch dashboard
streamlit run app.py
```

---

## Evaluation Results

Run `python run_evaluation.py` to reproduce. Measured on a held-out test set of 25 transactions, not cherry-picked.

**Classification:**

| Category    | Precision | Recall | F1    | Support |
|-------------|-----------|--------|-------|---------|
| transient   | 1.000     | 1.000  | 1.000 | 12      |
| recoverable | 1.000     | 1.000  | 1.000 | 8       |
| terminal    | 1.000     | 1.000  | 1.000 | 4       |
| suspicious  | 1.000     | 1.000  | 1.000 | 1       |

> 100% accuracy is because the classifier falls back to a deterministic error-code lookup table when no trained model exists. This is by design — the ML model is a future upgrade path. The rule-based classifier is already correct for all 17 known Razorpay error codes.

**Recovery Pipeline:**

| Metric           | Value                    |
|------------------|--------------------------|
| Recovery rate    | 59.9% (simulated)        |
| Amount recovered | Rs 52,816 / Rs 88,192    |
| Escalation rate  | 20.0%                    |
| Exceptions       | 6 / 25 unrecoverable     |

> Recovery outcomes are simulated because Razorpay test mode cannot execute real retries. Classification and strategy selection are fully real.

---

## Safety & Compliance

| Guardrail | Implementation |
|-----------|----------------|
| **Bounded actions** | Only 6 actions in `config.ALLOWED_ACTIONS`. Agent cannot hallucinate a refund or issue credit. |
| **Escalation chain** | retry → payment link → PayLater → human. Levels cannot be skipped. |
| **Stopping rules** | Max 3 retries. 4-hour cooldown. Max 3 customer touchpoints. |
| **Suspicious payments** | Always escalated to human review. No automated retry, ever. |
| **Audit trail** | Every decision: payment_id, action, reasoning, confidence, timestamp, outcome. |
| **No micro-credit** | Uses Razorpay PayLater (NBFC-compliant) instead of unauthorized credit. |

---

## Message Samples

```
┌─────────────────────────────────────────────────────────────────────────┐
│ HINGLISH (Card Declined)                                                │
│ "Hi Rahul! Aapka Rs 1,499 ka payment process nahi ho paya.             │
│  Koi baat nahi — is link se UPI se try karein: [link]"                  │
├─────────────────────────────────────────────────────────────────────────┤
│ HINDI (Bank Timeout)                                                    │
│ "Namaste Amit! Bank timeout ki wajah se payment ruk gaya.              │
│  Hum automatically retry kar rahe hain."                                │
├─────────────────────────────────────────────────────────────────────────┤
│ ENGLISH (Insufficient Funds)                                            │
│ "Hi Priya! Your payment of Rs 2,499 failed due to low balance.         │
│  Use Razorpay PayLater to clear it now and pay next month: [link]"     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
recover_ai/
│
├── server.py                  FastAPI webhook server
├── app.py                     Streamlit monitoring dashboard
├── config.py                  Settings, allowed actions, escalation chain
├── run_evaluation.py          End-to-end evaluation on held-out test set
│
├── src/
│   ├── classifier.py          RandomForest + rule-based fallback
│   ├── recovery_agent.py      Strategy engine with guardrails
│   ├── message_generator.py   English / Hindi / Hinglish templates
│   ├── retry_engine.py        Executes actions via Razorpay SDK
│   ├── escalation.py          Escalation chain + stopping rules
│   ├── audit.py               SQLite audit trail
│   └── razorpay_client.py     SDK wrapper + mock client for testing
│
├── scripts/
│   └── offline_optimizer.py   Daily Gemini template optimization
│
├── tests/
│   └── test_core.py           47 unit tests (all passing)
│
├── data/
│   ├── bank_error_codes.json  17 Razorpay error codes → categories
│   ├── generate_synthetic.py  Realistic Indian payment data generator
│   └── optimized_templates.json  LLM-generated Hinglish templates
│
└── docs/
    └── architecture_and_defense.md  Design decisions document
```

## Tech Stack

| Component   | Choice               | Why                                              |
|-------------|----------------------|--------------------------------------------------|
| Server      | FastAPI + Uvicorn    | Async, fast, native Pydantic validation          |
| Classifier  | scikit-learn (RF)    | Sub-millisecond inference, no GPU needed          |
| LLM         | Gemini 3.5 Flash     | Offline only, free tier sufficient for batch work |
| Payments    | Razorpay Python SDK  | Official SDK, test mode support                   |
| Audit       | SQLite               | Zero config, single file, portable                |
| Dashboard   | Streamlit + Plotly   | Rapid prototyping, built-in charting              |

## Limitations (honest)

- Recovery outcomes are simulated — Razorpay test mode does not support real payment retries
- The ML classifier currently falls back to a lookup table — a trained model would improve on ambiguous error codes
- SQLite will not scale past ~100 concurrent webhook writes — production would need PostgreSQL
- Single-process server — production would need worker processes behind a load balancer
- The offline optimizer requires a Gemini API key — without it, static templates still work

---

<div align="center">

**Built for Razorpay AI Buildathon 2026 — Track 3: Revenue Recovery**

[Website](https://nikunjtrehan.github.io/recover-ai/) · [Architecture Doc](docs/architecture_and_defense.md)

</div>
