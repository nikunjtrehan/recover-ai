# RecoverAI: Architecture and Design Decisions

> Razorpay AI Buildathon 2026 — Track 3: AI Revenue Recovery

This document explains why RecoverAI is built the way it is. Not what it does (see README), but why each decision was made and what alternatives were rejected.

---

## 1. The problem

Failed payments are not lost customers. They are recoverable revenue stuck behind infrastructure friction (bank timeouts, gateway errors) or liquidity friction (insufficient funds, expired cards).

Current recovery approaches are broken:
- Blind retry every N hours. Card networks flag this as abuse and block the merchant.
- Generic "update your payment method" email. Single-digit open rates.
- No differentiation between a UPI timeout (retry in 5 minutes) and a stolen card flag (never retry, escalate immediately).

## 2. Two-path architecture

The core design decision: separate the fast path from the smart path.

**Why not put the LLM in the transaction path?**

Three reasons, in order of severity:

1. **Availability.** If your LLM provider has an outage, your payment recovery pipeline goes down. Razorpay processes millions of transactions daily. A 30-minute OpenAI outage means thousands of unrecovered payments.

2. **Latency.** A Gemini API call takes 1-4 seconds. A RandomForest inference takes <1ms. The webhook response window is tight. Every millisecond of delay is a customer who closes the tab.

3. **Cost.** At Rs 0.01-0.05 per LLM call, processing 100K daily failures costs Rs 1,000-5,000/day. The RandomForest + rules engine costs zero per inference.

So the LLM runs offline. It reads yesterday's audit logs, analyzes which message templates converted and which didn't, and rewrites the templates using behavioral economics principles. The improved templates are saved to disk and picked up by the hot path the next day.

The hot path is a pure Python pipeline: classify the error, pick the action from a bounded set, fill a template, send it. No network calls except to Razorpay's own API.

## 3. Why RandomForest, not deep learning

The input is tabular: error code, payment method, amount, retry count, time of day. There are 4 output categories: transient, recoverable, terminal, suspicious.

For tabular classification with discrete features and small datasets, tree-based ensembles consistently outperform neural networks. This is well-established in the ML literature (see: "Why do tree-based models still outperform deep learning on tabular data?" — Grinsztajn et al., NeurIPS 2022).

The classifier currently falls back to a deterministic lookup table (`bank_error_codes.json`) when no trained model file exists. This is intentional: the lookup table is already 100% accurate for known error codes. The ML model is an upgrade path for ambiguous cases and new error codes that don't appear in our mapping.

## 4. Bounded actions and guardrails

The system can only execute actions from this list:
- `retry_payment` — resubmit the payment after a calculated delay
- `send_payment_link` — create a Razorpay Payment Link with an alternative method
- `offer_razorpay_paylater` — route to Razorpay's NBFC-compliant PayLater product
- `negotiate_retention` — offer merchant-configured retention incentives
- `escalate_to_human` — flag for manual review
- `no_action` — do nothing (terminal failures, suspicious activity)

Any output from the LLM or rules engine that is not in this list is rejected and falls back to `escalate_to_human`. This is enforced in `recovery_agent.py._enforce_guardrails()`.

**Why PayLater instead of micro-credit?**

An earlier version of this system offered "just-in-time micro-credit" to cover insufficient-funds failures. This was removed because:
- Issuing credit requires an NBFC license under RBI guidelines. A payment gateway cannot legally lend money.
- Razorpay already has a PayLater product backed by licensed NBFC partners. Routing the customer to PayLater achieves the same outcome without regulatory risk.

## 5. Stopping rules and escalation

- Max 3 retries per payment. NPCI guidelines prohibit excessive retries on UPI.
- 4-hour cooldown between retry attempts. Prevents network abuse flags.
- Max 3 customer touchpoints (messages). Beyond that, you are spamming.
- Suspicious payments (`FRAUD_RISK`, `RISK_CHECK_FAILED`) bypass all automated logic and go directly to human review. No exceptions.
- The escalation chain is `retry → payment_link → paylater → human`. It cannot be reordered or skipped.

## 6. Hinglish localization

Urban Indian consumers exhibit extreme banner-blindness to formal English banking messages. "Dear Customer, your payment of INR 1,499 has failed" gets ignored.

RecoverAI generates messages in conversational Hinglish:
> "Hi Rahul! Aapka Rs 1,499 ka payment process nahi ho paya. Koi baat nahi — is link se UPI se try karein"

Templates exist in English, Hindi, and Hinglish. The customer's language preference is read from the payment metadata. The offline optimizer rewrites Hinglish templates using Gemini to apply behavioral economics nudges (loss aversion, social proof, urgency framing).

## 7. Audit trail

Every decision is logged to SQLite (`recover_ai.db`) with:
- `payment_id` — which payment this decision was for
- `action` — what action was taken
- `reasoning` — why (human-readable explanation from the rules engine)
- `confidence` — classifier confidence score
- `timestamp` — when the decision was made
- `outcome` — what happened (updated asynchronously when `payment.captured` webhook fires)

This satisfies the buildathon requirement for "full audit trail" and the RBI requirement for traceable automated financial decisions.

## 8. What we did not build (and why)

- **Real-time LLM inference.** Rejected for latency, cost, and reliability reasons. See section 2.
- **Micro-credit issuance.** Rejected for regulatory reasons. See section 4.
- **Discount negotiation.** An earlier version dynamically offered 15% discounts. This creates a perverse incentive: customers learn to fail payments intentionally to get a discount. Removed. Kept as a "path to production" feature gated behind merchant configuration.
- **Custom ML model training.** The lookup table works. A trained model is an improvement, not a requirement. YAGNI.
- **Multi-merchant support.** Single-tenant for the hackathon. Production would need tenant isolation.

## 9. Limitations

1. Recovery outcomes are simulated. Razorpay test mode cannot execute real payment retries.
2. Synthetic training data (70 transactions). Production needs thousands of real failure logs.
3. SQLite does not scale past ~100 concurrent writes. Production needs PostgreSQL.
4. Single-process server. Production needs Uvicorn workers behind a reverse proxy.
5. No rate limiting on the webhook endpoint. Production needs per-merchant rate limits.

## 10. References

1. Grinsztajn, L., Oyallon, E., & Varoquaux, G. (2022). "Why do tree-based models still outperform deep learning on tabular data?" NeurIPS 2022.
2. Stripe Engineering Blog (2023). "How Stripe uses machine learning to recover revenue."
3. Netflix TechBlog (2021). "ML Observability in Payment Systems."
4. NPCI Operating Guidelines — UPI retry and timeout specifications.
5. RBI Master Direction on Digital Lending (2022) — NBFC licensing requirements for credit issuance.
