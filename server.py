"""FastAPI Webhook Server — receives Razorpay webhook events.

Listens for:
- payment.failed: Triggers the recovery pipeline
- subscription.halted: Triggers subscription recovery
- payment.captured: Updates recovery outcome to success

Run with:
    uvicorn server:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import logging
from datetime import datetime

from config import settings
from src.audit import AuditTrail
from src.classifier import FailureClassifier
from src.recovery_agent import RecoveryAgent
from src.retry_engine import RetryEngine
from src.escalation import EscalationManager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RecoverAI")

# Initialize FastAPI app
app = FastAPI(
    title="RecoverAI Webhook Server",
    description="Receives Razorpay webhook events and triggers AI-powered recovery",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
audit = AuditTrail()
classifier = FailureClassifier()
agent = RecoveryAgent(audit_trail=audit, classifier=classifier)
engine = RetryEngine(audit_trail=audit)
escalation = EscalationManager(audit_trail=audit)


class WebhookPayload(BaseModel):
    """Razorpay webhook event payload."""
    event: str
    payload: Dict[str, Any]
    account_id: Optional[str] = None


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "RecoverAI",
        "status": "running",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/webhook")
async def handle_webhook(request: Request):
    """Handle incoming Razorpay webhook events.
    
    Processes:
    - payment.failed → triggers recovery pipeline
    - subscription.halted → triggers subscription recovery
    - payment.captured → marks recovery as successful
    """
    try:
        body = await request.body()
        payload = json.loads(body)
        
        event = payload.get("event", "")
        event_data = payload.get("payload", {})
        
        logger.info(f"Received webhook: {event}")
        
        if event == "payment.failed":
            return await _handle_payment_failed(event_data)
        elif event == "subscription.halted":
            return await _handle_subscription_halted(event_data)
        elif event == "payment.captured":
            return await _handle_payment_captured(event_data)
        else:
            logger.info(f"Ignoring event: {event}")
            return {"status": "ignored", "event": event}
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _handle_payment_failed(event_data: Dict[str, Any]):
    """Process a failed payment through the recovery pipeline."""
    payment_entity = event_data.get("payment", {}).get("entity", {})
    
    # Convert to our internal format
    payment = {
        "payment_id": payment_entity.get("id", "unknown"),
        "order_id": payment_entity.get("order_id"),
        "amount": payment_entity.get("amount", 0) / 100,  # Paise to rupees
        "currency": payment_entity.get("currency", "INR"),
        "method": payment_entity.get("method", "unknown"),
        "error_code": payment_entity.get("error_code", "UNKNOWN"),
        "error_description": payment_entity.get("error_description", ""),
        "customer": {
            "name": payment_entity.get("notes", {}).get("customer_name", "Customer"),
            "email": payment_entity.get("email", ""),
            "phone": payment_entity.get("contact", ""),
            "language_pref": payment_entity.get("notes", {}).get("language_pref", "english"),
        },
        "created_at": datetime.utcnow().isoformat() + "Z",
        "retry_count": 0,
    }
    
    # Check stopping rules
    should_stop, stop_reason = escalation.should_stop(payment)
    if should_stop:
        logger.info(f"Stopping recovery for {payment['payment_id']}: {stop_reason}")
        return {"status": "stopped", "reason": stop_reason}
    
    # Run recovery pipeline
    strategy = agent.determine_strategy(payment)
    result = engine.execute_strategy(payment, strategy)
    
    logger.info(
        f"Recovery action for {payment['payment_id']}: "
        f"{strategy['action']} -> {result.get('outcome', 'unknown')}"
    )
    
    return {
        "status": "processed",
        "payment_id": payment["payment_id"],
        "action": strategy["action"],
        "outcome": result.get("outcome"),
    }


async def _handle_subscription_halted(event_data: Dict[str, Any]):
    """Process a halted subscription."""
    subscription = event_data.get("subscription", {}).get("entity", {})
    
    payment = {
        "payment_id": f"sub_{subscription.get('id', 'unknown')}",
        "subscription_id": subscription.get("id"),
        "amount": subscription.get("current_end", 0),
        "method": "subscription",
        "error_code": "MANDATE_NOT_FOUND",
        "error_description": "Subscription halted due to payment failure",
        "customer": {
            "name": "Subscriber",
            "email": subscription.get("customer_email", ""),
            "phone": subscription.get("customer_phone", ""),
            "language_pref": "english",
        },
        "created_at": datetime.utcnow().isoformat() + "Z",
        "retry_count": 0,
    }
    
    strategy = agent.determine_strategy(payment)
    result = engine.execute_strategy(payment, strategy)
    
    return {
        "status": "processed",
        "subscription_id": subscription.get("id"),
        "action": strategy["action"],
    }


async def _handle_payment_captured(event_data: Dict[str, Any]):
    """Mark a recovered payment as successful."""
    payment_entity = event_data.get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id", "unknown")
    amount = payment_entity.get("amount", 0) / 100
    
    # Update any pending audit entries for this payment
    entries = audit.get_entries_by_payment(payment_id)
    for entry in entries:
        if entry["outcome"] == "pending":
            audit.update_outcome(
                entry["id"],
                outcome="success",
                outcome_detail="Payment captured successfully",
                recovery_amount=amount,
            )
    
    logger.info(f"Payment {payment_id} recovered: ₹{amount}")
    return {"status": "recovered", "payment_id": payment_id, "amount": amount}


# API endpoints for the dashboard
@app.get("/api/summary")
async def get_summary():
    """Get recovery summary statistics."""
    return audit.get_recovery_summary()


@app.get("/api/audit")
async def get_audit_log(limit: int = 50):
    """Get audit log entries."""
    entries = audit.get_all_entries()
    return {"entries": entries[:limit], "total": len(entries)}


@app.get("/api/audit/{payment_id}")
async def get_payment_audit(payment_id: str):
    """Get audit trail for a specific payment."""
    entries = audit.get_entries_by_payment(payment_id)
    timeline = escalation.get_payment_timeline(payment_id)
    return {"entries": entries, "timeline": timeline}


@app.get("/api/queue")
async def get_escalation_queue():
    """Get the human escalation queue."""
    return {"queue": engine.get_human_queue()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.webhook_port)
