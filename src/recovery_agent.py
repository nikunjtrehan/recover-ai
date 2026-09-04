"""Recovery Agent — LLM-powered recovery strategy engine.

The brain of RecoverAI. Uses an LLM to:
1. Analyze classified failures + customer context
2. Determine optimal recovery strategy
3. Choose retry timing
4. Generate recovery rationale
5. Ensure all actions are BOUNDED (only allowed actions)

Every decision is logged to the audit trail with full reasoning.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings, ALLOWED_ACTIONS, ESCALATION_CHAIN, FAILURE_CATEGORIES
from src.audit import AuditTrail
from src.classifier import FailureClassifier


# System prompt for the recovery agent
RECOVERY_AGENT_PROMPT = """You are RecoverAI, an intelligent payment recovery agent for Indian merchants using Razorpay.

Your job is to analyze failed payments and determine the optimal recovery strategy.

RULES (STRICT — NEVER VIOLATE):
1. You can ONLY recommend these actions: {allowed_actions}
2. Maximum retry attempts: {max_retries}
3. Minimum cooldown between attempts: {cooldown_hours} hours
4. For INSUFFICIENT_FUNDS failures where the customer LTV > ₹1000, use 'offer_razorpay_paylater' to route them to Razorpay's BNPL ecosystem.
5. For CARD_EXPIRED or repeated failures suggesting churn, use 'negotiate_retention' to offer a 15% discount if they update their payment method today.
6. NEVER skip an escalation level unless injecting paylater or negotiation.
7. NEVER recommend an action for "suspicious" failures — always escalate_to_human.
8. For "terminal" failures — only send_payment_link, offer_razorpay_paylater, negotiate_retention, or escalate_to_human.

Given the payment failure context below, respond with a JSON object:
{{
    "action": "<one of: retry_payment, send_payment_link, offer_razorpay_paylater, negotiate_retention, escalate_to_human, no_action>",
    "reasoning": "<detailed explanation of why this action was chosen>",
    "retry_delay_minutes": <number, only if action is retry_payment>,
    "alternative_method": "<suggested payment method if sending link, e.g., 'upi', 'card', 'netbanking'>",
    "urgency": "<low/medium/high>",
    "customer_message_tone": "<empathetic/reminder/urgent/negotiation>"
}}

PAYMENT FAILURE CONTEXT:
- Payment ID: {payment_id}
- Amount: ₹{amount}
- Method: {method}
- Error Code: {error_code}
- Error Description: {error_description}
- Failure Category: {failure_category} ({category_description})
- Classification Confidence: {confidence:.1%}
- Retry Count So Far: {retry_count}/{max_retries}
- Customer Name: {customer_name}
- Customer LTV (Lifetime Value): ₹{customer_ltv}
- Customer Language Preference: {language_pref}
- Time of Failure: {failure_time}
- Day of Week: {day_of_week}

Respond ONLY with the JSON object. No markdown, no extra text."""


class RecoveryAgent:
    """LLM-powered recovery strategy engine."""
    
    def __init__(self, audit_trail: AuditTrail = None, classifier: FailureClassifier = None):
        self.audit = audit_trail or AuditTrail()
        self.classifier = classifier or FailureClassifier()
        self.llm = self._init_llm()
    
    def _init_llm(self):
        """Initialize the LLM based on provider setting."""
        if not settings.use_llm_in_hot_path:
            return None  # Force <5ms rules engine for production latency
            
        provider = settings.llm_provider.lower()
        
        try:
            if provider == "openai":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model="gpt-4o-mini",
                    temperature=0.1,
                    api_key=settings.openai_api_key,
                )
            elif provider == "anthropic":
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(
                    model="claude-3-haiku-20240307",
                    temperature=0.1,
                    api_key=settings.anthropic_api_key,
                )
            elif provider == "google":
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(
                    model="gemini-3.5-flash",
                    temperature=0.1,
                    google_api_key=settings.google_api_key,
                )
            else:
                return None  # Fallback to rule-based
        except Exception:
            return None  # Fallback to rule-based
    
    def determine_strategy(self, payment: Dict[str, Any]) -> Dict[str, Any]:
        """Determine the optimal recovery strategy for a failed payment.
        
        Args:
            payment: Payment failure record with all context
            
        Returns:
            Strategy dict with action, reasoning, and parameters
        """
        # Step 1: Classify the failure
        category, confidence, probabilities = self.classifier.classify(payment)
        
        # Step 2: Check guardrails BEFORE asking the LLM
        retry_count = int(payment.get("retry_count", 0))
        
        # Hard guardrail: max retries exceeded
        if retry_count >= settings.max_retries:
            if category in ["transient", "recoverable"]:
                # Force escalation to payment link
                strategy = self._create_strategy(
                    action="send_payment_link",
                    reasoning=f"Max retry limit ({settings.max_retries}) reached. "
                              f"Escalating to payment link with alternative method.",
                    confidence=confidence,
                    urgency="high",
                )
                self._log_strategy(payment, category, confidence, strategy)
                return strategy
            else:
                strategy = self._create_strategy(
                    action="escalate_to_human",
                    reasoning=f"Max retries reached and failure is {category}. Human review needed.",
                    confidence=confidence,
                    urgency="high",
                )
                self._log_strategy(payment, category, confidence, strategy)
                return strategy
        
        # Hard guardrail: suspicious = always escalate
        if category == "suspicious":
            strategy = self._create_strategy(
                action="escalate_to_human",
                reasoning="Payment flagged as suspicious. Mandatory human review per policy.",
                confidence=confidence,
                urgency="high",
            )
            self._log_strategy(payment, category, confidence, strategy)
            return strategy
        
        # Step 3: Ask the LLM for nuanced strategy (or use rules as fallback)
        if self.llm is not None:
            strategy = self._llm_strategy(payment, category, confidence)
        else:
            strategy = self._rule_based_strategy(payment, category, confidence)
        
        # Step 4: Validate LLM output against guardrails
        strategy = self._enforce_guardrails(strategy, payment, category, retry_count)
        
        # Step 5: Log to audit trail
        self._log_strategy(payment, category, confidence, strategy)
        
        return strategy
    
    def _llm_strategy(self, payment: Dict[str, Any], category: str,
                      confidence: float) -> Dict[str, Any]:
        """Get strategy from LLM."""
        # Build the prompt
        customer = payment.get("customer", {})
        created_at = payment.get("created_at", "")
        
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            day_name = dt.strftime("%A")
            time_str = dt.strftime("%H:%M")
        except (ValueError, AttributeError):
            day_name = "Unknown"
            time_str = "Unknown"
        
        prompt = RECOVERY_AGENT_PROMPT.format(
            allowed_actions=", ".join(ALLOWED_ACTIONS),
            max_retries=settings.max_retries,
            cooldown_hours=settings.cooldown_hours,
            payment_id=payment.get("payment_id", "unknown"),
            amount=payment.get("amount", 0),
            method=payment.get("method", "unknown"),
            error_code=payment.get("error_code", "UNKNOWN"),
            error_description=payment.get("error_description", "Unknown error"),
            failure_category=category,
            category_description=FAILURE_CATEGORIES.get(category, ""),
            confidence=confidence,
            retry_count=payment.get("retry_count", 0),
            customer_name=customer.get("name", "Customer"),
            customer_ltv=customer.get("ltv", 5000),  # Default LTV 5000 for demo
            language_pref=customer.get("language_pref", "english"),
            failure_time=time_str,
            day_of_week=day_name,
        )
        
        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            
            # Parse JSON from response
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            result = json.loads(content)
            
            return self._create_strategy(
                action=result.get("action", "escalate_to_human"),
                reasoning=result.get("reasoning", "LLM provided no reasoning"),
                confidence=confidence,
                retry_delay_minutes=result.get("retry_delay_minutes"),
                alternative_method=result.get("alternative_method"),
                urgency=result.get("urgency", "medium"),
                message_tone=result.get("customer_message_tone", "empathetic"),
            )
        except Exception as e:
            # Fallback to rule-based on any LLM error
            return self._rule_based_strategy(
                payment, category, confidence,
                fallback_reason=f"LLM error: {str(e)}"
            )
    
    def _rule_based_strategy(self, payment: Dict[str, Any], category: str,
                             confidence: float, fallback_reason: str = None) -> Dict[str, Any]:
        """Deterministic rule-based strategy as LLM fallback."""
        error_code = payment.get("error_code", "UNKNOWN")
        retry_count = int(payment.get("retry_count", 0))
        method = payment.get("method", "unknown")
        
        # Determine action based on category and retry count
        if category == "transient":
            if retry_count < settings.max_retries:
                delay = self.error_code_map_delay(error_code)
                reasoning = (f"Transient failure ({error_code}). "
                           f"Retry #{retry_count + 1} scheduled in {delay} minutes.")
                if fallback_reason:
                    reasoning += f" [Fallback: {fallback_reason}]"
                return self._create_strategy(
                    action="retry_payment",
                    reasoning=reasoning,
                    confidence=confidence,
                    retry_delay_minutes=delay,
                    urgency="medium",
                )
            else:
                return self._create_strategy(
                    action="send_payment_link",
                    reasoning=f"Transient failure but max retries ({settings.max_retries}) reached.",
                    confidence=confidence,
                    alternative_method="upi" if method != "upi" else "card",
                    urgency="high",
                )
        
        elif category == "recoverable":
            alt_method = "upi" if method != "upi" else "card"
            return self._create_strategy(
                action="send_payment_link",
                reasoning=f"Recoverable failure ({error_code}). Sending payment link with {alt_method}.",
                confidence=confidence,
                alternative_method=alt_method,
                urgency="medium",
                message_tone="empathetic",
            )
        
        elif category == "terminal":
            if error_code in ["CARD_EXPIRED", "INVALID_VPA", "MANDATE_NOT_FOUND"]:
                return self._create_strategy(
                    action="send_payment_link",
                    reasoning=f"Terminal failure ({error_code}) but recoverable via new payment method.",
                    confidence=confidence,
                    alternative_method="upi",
                    urgency="high",
                    message_tone="empathetic",
                )
            return self._create_strategy(
                action="escalate_to_human",
                reasoning=f"Terminal failure ({error_code}). Requires human review.",
                confidence=confidence,
                urgency="high",
            )
        
        else:  # suspicious
            return self._create_strategy(
                action="escalate_to_human",
                reasoning="Suspicious activity detected. Mandatory human review.",
                confidence=confidence,
                urgency="high",
            )
    
    def error_code_map_delay(self, error_code: str) -> int:
        """Get recommended retry delay from error code map."""
        if error_code in self.classifier.error_code_map:
            return self.classifier.error_code_map[error_code].get(
                "optimal_retry_delay_minutes", 30
            )
        return 30  # Default 30 minutes
    
    def _create_strategy(self, action: str, reasoning: str, confidence: float,
                         retry_delay_minutes: int = None,
                         alternative_method: str = None,
                         urgency: str = "medium",
                         message_tone: str = "empathetic") -> Dict[str, Any]:
        """Create a standardized strategy dict."""
        return {
            "action": action,
            "reasoning": reasoning,
            "confidence": confidence,
            "retry_delay_minutes": retry_delay_minutes,
            "alternative_method": alternative_method,
            "urgency": urgency,
            "message_tone": message_tone,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    
    def _enforce_guardrails(self, strategy: Dict[str, Any], payment: Dict[str, Any],
                           category: str, retry_count: int) -> Dict[str, Any]:
        """Enforce hard guardrails on the strategy — overrides LLM if needed."""
        action = strategy.get("action", "")
        
        # Guardrail 1: Action must be in allowed list
        if action not in ALLOWED_ACTIONS:
            strategy["action"] = "escalate_to_human"
            strategy["reasoning"] += f" [GUARDRAIL: Invalid action '{action}' overridden to escalate_to_human]"
        
        # Guardrail 2: Can't retry if max retries reached
        if action == "retry_payment" and retry_count >= settings.max_retries:
            strategy["action"] = "send_payment_link"
            strategy["reasoning"] += f" [GUARDRAIL: Max retries reached, escalated to payment link]"
        
        # Guardrail 3: Suspicious must always escalate
        if category == "suspicious" and action != "escalate_to_human":
            strategy["action"] = "escalate_to_human"
            strategy["reasoning"] += " [GUARDRAIL: Suspicious payment, forced escalation]"
        
        return strategy
    
    def _log_strategy(self, payment: Dict[str, Any], category: str,
                      confidence: float, strategy: Dict[str, Any]):
        """Log the strategy decision to the audit trail."""
        customer = payment.get("customer", {})
        self.audit.log_action(
            payment_id=payment.get("payment_id", "unknown"),
            action=strategy["action"],
            agent_reasoning=strategy["reasoning"],
            confidence=confidence,
            order_id=payment.get("order_id"),
            amount=float(payment.get("amount", 0)),
            error_code=payment.get("error_code"),
            failure_category=category,
            action_detail=json.dumps({
                "retry_delay": strategy.get("retry_delay_minutes"),
                "alt_method": strategy.get("alternative_method"),
                "urgency": strategy.get("urgency"),
            }),
            retry_attempt=int(payment.get("retry_count", 0)),
            escalation_level=strategy["action"],
            message_language=customer.get("language_pref", "english"),
        )
