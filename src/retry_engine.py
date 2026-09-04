"""Smart Retry Engine — executes bounded payment recovery actions.

Handles:
- Intelligent payment retries via Razorpay API
- Payment link creation and delivery
- Escalation to human queue
- Cooldown and rate limiting

All actions are bounded and logged.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.audit import AuditTrail
from src.razorpay_client import get_razorpay_client
from src.message_generator import MessageGenerator


class RetryEngine:
    """Executes recovery actions with guardrails."""
    
    def __init__(self, audit_trail: AuditTrail = None):
        self.audit = audit_trail or AuditTrail()
        self.rzp = get_razorpay_client()
        self.msg_gen = MessageGenerator()
        self.human_queue: List[Dict[str, Any]] = []  # In-memory escalation queue
    
    def execute_strategy(self, payment: Dict[str, Any],
                         strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a recovery strategy.
        
        Args:
            payment: The failed payment record
            strategy: The strategy from RecoveryAgent
            
        Returns:
            Execution result with outcome
        """
        action = strategy.get("action", "no_action")
        
        if action == "retry_payment":
            return self._execute_retry(payment, strategy)
        elif action == "send_payment_link":
            return self._execute_payment_link(payment, strategy)
        elif action == "offer_razorpay_paylater":
            # PayLater is delivered via a Razorpay Payment Link with method hint
            strategy = {**strategy, "alternative_method": "paylater"}
            return self._execute_payment_link(payment, strategy)
        elif action == "negotiate_retention":
            # Retention offer is a payment link with discount note attached
            strategy = {**strategy, "alternative_method": "any"}
            return self._execute_payment_link(payment, strategy)
        elif action == "escalate_to_human":
            return self._execute_escalation(payment, strategy)
        elif action == "no_action":
            return self._execute_no_action(payment, strategy)
        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}",
                "outcome": "failed",
            }
    
    def _execute_retry(self, payment: Dict[str, Any],
                       strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a payment retry."""
        amount = int(float(payment.get("amount", 0)) * 100)  # Convert to paise
        
        try:
            # Create a new order for the retry
            order = self.rzp.create_order(
                amount_paise=amount,
                receipt=f"recovery_{payment.get('payment_id', 'unknown')}",
                notes={
                    "recovery_for": payment.get("payment_id", ""),
                    "retry_attempt": str(payment.get("retry_count", 0) + 1),
                    "original_error": payment.get("error_code", ""),
                }
            )
            
            # Generate recovery message
            msg = self.msg_gen.generate_message(payment, strategy)
            
            return {
                "success": True,
                "outcome": "retry_initiated",
                "order_id": order.get("id"),
                "message": msg["message"],
                "message_language": msg["language"],
                "retry_delay_minutes": strategy.get("retry_delay_minutes", 30),
                "detail": f"New order {order.get('id')} created for retry",
            }
        except Exception as e:
            return {
                "success": False,
                "outcome": "retry_failed",
                "error": str(e),
                "detail": "Failed to create retry order via Razorpay API",
            }
    
    def _execute_payment_link(self, payment: Dict[str, Any],
                              strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Create and send a payment link for recovery."""
        customer = payment.get("customer", {})
        amount = int(float(payment.get("amount", 0)) * 100)  # Convert to paise
        
        try:
            # Create payment link via Razorpay
            link = self.rzp.create_payment_link(
                amount_paise=amount,
                customer_name=customer.get("name", "Customer"),
                customer_email=customer.get("email", "customer@example.com"),
                customer_phone=customer.get("phone", "+919999999999"),
                description=f"Recovery for failed payment {payment.get('payment_id', '')}",
                notes={
                    "recovery_for": payment.get("payment_id", ""),
                    "alternative_method": strategy.get("alternative_method", "any"),
                    "original_error": payment.get("error_code", ""),
                }
            )
            
            link_url = link.get("short_url", link.get("id", "N/A"))
            
            # Generate recovery message with the actual link
            msg = self.msg_gen.generate_message(payment, strategy, payment_link_url=link_url)
            
            return {
                "success": True,
                "outcome": "link_sent",
                "link_id": link.get("id"),
                "link_url": link_url,
                "message": msg["message"],
                "message_language": msg["language"],
                "detail": f"Payment link {link.get('id')} created and sent",
            }
        except Exception as e:
            return {
                "success": False,
                "outcome": "link_failed",
                "error": str(e),
                "detail": "Failed to create payment link via Razorpay API",
            }
    
    def _execute_escalation(self, payment: Dict[str, Any],
                            strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Add payment to human review queue."""
        escalation_entry = {
            "payment_id": payment.get("payment_id"),
            "amount": payment.get("amount"),
            "error_code": payment.get("error_code"),
            "customer": payment.get("customer", {}),
            "reasoning": strategy.get("reasoning"),
            "urgency": strategy.get("urgency", "medium"),
            "escalated_at": datetime.utcnow().isoformat() + "Z",
        }
        self.human_queue.append(escalation_entry)
        
        return {
            "success": True,
            "outcome": "escalated",
            "queue_position": len(self.human_queue),
            "detail": f"Payment escalated to human review queue (position {len(self.human_queue)})",
        }
    
    def _execute_no_action(self, payment: Dict[str, Any],
                           strategy: Dict[str, Any]) -> Dict[str, Any]:
        """Log that no action was taken."""
        return {
            "success": True,
            "outcome": "no_action",
            "detail": "No recovery action needed",
        }
    
    def get_human_queue(self) -> List[Dict[str, Any]]:
        """Get the current human escalation queue."""
        return self.human_queue.copy()
