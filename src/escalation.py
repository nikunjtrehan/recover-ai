"""Escalation Handler — manages the escalation chain and stopping rules.

Implements compliant escalation:
1. retry_payment (up to max_retries)
2. send_payment_link (alternative payment method)
3. escalate_to_human (manual review)

Stopping Rules:
- Max 3 retries per payment
- Minimum 4-hour cooldown between attempts
- Suspicious payments always escalate immediately
- No more than 3 total touchpoints per customer per payment
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings, ESCALATION_CHAIN
from src.audit import AuditTrail


class EscalationManager:
    """Manages escalation chains and stopping rules."""
    
    MAX_TOUCHPOINTS = 3  # Max total contacts per customer per payment
    
    def __init__(self, audit_trail: AuditTrail = None):
        self.audit = audit_trail or AuditTrail()
    
    def get_next_escalation_level(self, payment_id: str,
                                   current_action: str) -> Optional[str]:
        """Determine the next escalation level based on history."""
        # Get history for this payment
        history = self.audit.get_entries_by_payment(payment_id)
        
        # Count total touchpoints
        touchpoints = len([e for e in history if e["action"] != "no_action"])
        
        if touchpoints >= self.MAX_TOUCHPOINTS:
            return None  # Stop — max touchpoints reached
        
        # Find current position in escalation chain
        try:
            current_idx = ESCALATION_CHAIN.index(current_action)
        except ValueError:
            current_idx = -1
        
        # Return next level
        next_idx = current_idx + 1
        if next_idx < len(ESCALATION_CHAIN):
            return ESCALATION_CHAIN[next_idx]
        
        return None  # Already at max escalation
    
    def should_stop(self, payment: Dict[str, Any]) -> Tuple[bool, str]:
        """Check if recovery attempts should stop for this payment.
        
        Returns:
            Tuple of (should_stop: bool, reason: str)
        """
        payment_id = payment.get("payment_id", "")
        history = self.audit.get_entries_by_payment(payment_id)
        
        # Rule 1: Max touchpoints
        touchpoints = len([e for e in history if e["action"] != "no_action"])
        if touchpoints >= self.MAX_TOUCHPOINTS:
            return True, f"Max touchpoints ({self.MAX_TOUCHPOINTS}) reached"
        
        # Rule 2: Already escalated to human
        human_escalations = [e for e in history if e["action"] == "escalate_to_human"]
        if human_escalations:
            return True, "Already escalated to human review"
        
        # Rule 3: Payment already recovered
        successful = [e for e in history if e["outcome"] == "success"]
        if successful:
            return True, "Payment already recovered"
        
        # Rule 4: Cooldown check
        if history:
            last_action = history[-1]
            last_time = datetime.fromisoformat(
                last_action["timestamp"].replace("Z", "+00:00")
            )
            cooldown = timedelta(hours=settings.cooldown_hours)
            if datetime.now(last_time.tzinfo) - last_time < cooldown:
                return True, f"Cooldown period ({settings.cooldown_hours}h) not elapsed"
        
        return False, "OK to proceed"
    
    def get_payment_timeline(self, payment_id: str) -> List[Dict[str, Any]]:
        """Get the full recovery timeline for a payment."""
        history = self.audit.get_entries_by_payment(payment_id)
        
        timeline = []
        for entry in history:
            timeline.append({
                "timestamp": entry["timestamp"],
                "action": entry["action"],
                "reasoning": entry["agent_reasoning"],
                "outcome": entry["outcome"],
                "confidence": entry["confidence"],
                "message": entry.get("message_generated"),
            })
        
        return timeline
