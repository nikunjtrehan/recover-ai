"""Razorpay SDK Wrapper — handles all payment API interactions in test mode.

Provides methods for:
- Creating orders and payments (test mode)
- Retrying failed payments
- Creating payment links for recovery
- Fetching payment and dispute details
- Webhook signature verification
"""

import razorpay
import hmac
import hashlib
from typing import Optional, Dict, Any
from datetime import datetime
import json
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
from config import settings


class RazorpayClient:
    """Wrapper around Razorpay Python SDK for test-mode operations."""
    
    def __init__(self):
        self.client = razorpay.Client(
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
        )
        # Verify we're in test mode
        if not settings.razorpay_key_id.startswith("rzp_test_"):
            raise ValueError(
                "RecoverAI must run in Razorpay TEST mode. "
                "Key ID must start with 'rzp_test_'. "
                "Never use live keys for the buildathon."
            )
    
    def create_order(self, amount_paise: int, currency: str = "INR",
                     receipt: str = None, notes: Dict = None) -> Dict[str, Any]:
        """Create a new order in test mode.
        
        Args:
            amount_paise: Amount in paise (₹100 = 10000 paise)
            currency: Currency code (default INR)
            receipt: Optional receipt ID
            notes: Optional metadata dict
        """
        data = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt or f"rcvr_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        }
        if notes:
            data["notes"] = notes
        
        return self.client.order.create(data=data)
    
    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        """Fetch payment details by ID."""
        return self.client.payment.fetch(payment_id)
    
    def create_payment_link(self, amount_paise: int, customer_name: str,
                            customer_email: str, customer_phone: str,
                            description: str = "Payment Recovery",
                            expire_by: int = None,
                            notes: Dict = None) -> Dict[str, Any]:
        """Create a payment link for recovery outreach.
        
        This is the primary recovery mechanism — send a new payment link
        to the customer with an alternative payment method.
        """
        data = {
            "amount": amount_paise,
            "currency": "INR",
            "description": description,
            "customer": {
                "name": customer_name,
                "email": customer_email,
                "contact": customer_phone,
            },
            "notify": {
                "sms": True,
                "email": True,
            },
            "reminder_enable": True,
        }
        if expire_by:
            data["expire_by"] = expire_by
        if notes:
            data["notes"] = notes
        
        return self.client.payment_link.create(data=data)
    
    def fetch_payment_link(self, link_id: str) -> Dict[str, Any]:
        """Fetch payment link status."""
        return self.client.payment_link.fetch(link_id)
    
    def fetch_all_payments(self, count: int = 50, skip: int = 0) -> Dict[str, Any]:
        """Fetch recent payments."""
        return self.client.payment.all({"count": count, "skip": skip})
    
    def fetch_settlement(self, settlement_id: str) -> Dict[str, Any]:
        """Fetch settlement details."""
        return self.client.settlement.fetch(settlement_id)
    
    def verify_webhook_signature(self, body: str, signature: str,
                                  secret: str) -> bool:
        """Verify Razorpay webhook signature.
        
        Args:
            body: Raw request body string
            signature: X-Razorpay-Signature header value
            secret: Webhook secret from Razorpay dashboard
        """
        try:
            self.client.utility.verify_webhook_signature(body, signature, secret)
            return True
        except razorpay.errors.SignatureVerificationError:
            return False


class MockRazorpayClient:
    """Mock client for local testing without Razorpay API keys.
    
    Returns realistic test data so the demo works even without valid API keys.
    Used when RAZORPAY_KEY_ID is set to the placeholder value.
    """
    
    def __init__(self):
        self._counter = 0
    
    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_test_mock_{self._counter:06d}"
    
    def create_order(self, amount_paise: int, currency: str = "INR",
                     receipt: str = None, notes: Dict = None) -> Dict[str, Any]:
        return {
            "id": self._next_id("order"),
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "status": "created",
        }
    
    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        return {
            "id": payment_id,
            "amount": 100000,
            "currency": "INR",
            "status": "failed",
            "method": "card",
            "error_code": "GATEWAY_ERROR",
        }
    
    def create_payment_link(self, amount_paise: int, customer_name: str,
                            customer_email: str, customer_phone: str,
                            description: str = "Payment Recovery",
                            expire_by: int = None,
                            notes: Dict = None) -> Dict[str, Any]:
        link_id = self._next_id("plink")
        return {
            "id": link_id,
            "amount": amount_paise,
            "currency": "INR",
            "description": description,
            "short_url": f"https://rzp.io/i/{link_id[-8:]}",
            "status": "created",
        }
    
    def fetch_payment_link(self, link_id: str) -> Dict[str, Any]:
        return {"id": link_id, "status": "created"}
    
    def fetch_all_payments(self, count: int = 50, skip: int = 0) -> Dict[str, Any]:
        return {"items": [], "count": 0}
    
    def fetch_settlement(self, settlement_id: str) -> Dict[str, Any]:
        return {"id": settlement_id, "amount": 0, "status": "processed"}
    
    def verify_webhook_signature(self, body: str, signature: str,
                                  secret: str) -> bool:
        return True


def get_razorpay_client():
    """Factory function — returns mock client if using placeholder keys."""
    if settings.razorpay_key_id == "rzp_test_placeholder":
        return MockRazorpayClient()
    return RazorpayClient()
