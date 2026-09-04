"""Unit tests for RecoverAI core components.

Run: python -m pytest tests/test_core.py -v
"""

import sys
import os
import json
import tempfile
from pathlib import Path

# Fix imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings, ALLOWED_ACTIONS, ESCALATION_CHAIN, FAILURE_CATEGORIES
from src.audit import AuditTrail
from src.classifier import FailureClassifier
from src.recovery_agent import RecoveryAgent
from src.message_generator import MessageGenerator
from src.escalation import EscalationManager
from src.razorpay_client import MockRazorpayClient


# ── Fixtures ──────────────────────────────────────────────

def make_payment(error_code="GATEWAY_ERROR", method="upi", amount=1500,
                 retry_count=0, language="english", name="Rahul Sharma"):
    """Build a minimal payment dict for testing."""
    return {
        "payment_id": f"pay_test_{error_code.lower()}",
        "order_id": "order_test_001",
        "amount": amount,
        "method": method,
        "error_code": error_code,
        "error_description": f"Test: {error_code}",
        "customer": {
            "name": name,
            "email": "test@example.com",
            "phone": "+919876543210",
            "language_pref": language,
            "ltv": 5000,
        },
        "created_at": "2026-09-03T12:00:00Z",
        "retry_count": retry_count,
    }


def make_audit(tmp_path=None):
    """Create an AuditTrail backed by a real temp file (not :memory:)."""
    if tmp_path is None:
        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
    return AuditTrail(db_path=tmp_path), tmp_path


# ── Config Tests ──────────────────────────────────────────

class TestConfig:
    def test_allowed_actions_complete(self):
        expected = {"retry_payment", "send_payment_link", "offer_razorpay_paylater",
                    "negotiate_retention", "escalate_to_human", "no_action"}
        assert set(ALLOWED_ACTIONS) == expected

    def test_escalation_chain_order(self):
        assert ESCALATION_CHAIN[0] == "retry_payment"
        assert ESCALATION_CHAIN[-1] == "escalate_to_human"
        assert "offer_razorpay_paylater" in ESCALATION_CHAIN

    def test_failure_categories(self):
        assert set(FAILURE_CATEGORIES.keys()) == {"transient", "recoverable", "terminal", "suspicious"}

    def test_llm_not_in_hot_path(self):
        assert settings.use_llm_in_hot_path is False


# ── Classifier Tests ──────────────────────────────────────

class TestClassifier:
    def setup_method(self):
        self.clf = FailureClassifier()

    def test_transient_codes(self):
        for code in ["GATEWAY_ERROR", "SERVER_ERROR", "NETWORK_ERROR", "BANK_TIMEOUT", "UPI_TIMEOUT", "NETBANKING_ERROR"]:
            cat, conf, _ = self.clf.classify(make_payment(error_code=code))
            assert cat == "transient", f"{code} should be transient, got {cat}"
            assert conf == 0.90

    def test_recoverable_codes(self):
        for code in ["INSUFFICIENT_FUNDS", "CARD_DECLINED", "AUTHENTICATION_FAILED",
                      "LIMIT_EXCEEDED", "MANDATE_NOT_FOUND", "PAYMENT_CANCELLED"]:
            cat, conf, _ = self.clf.classify(make_payment(error_code=code))
            assert cat == "recoverable", f"{code} should be recoverable, got {cat}"

    def test_terminal_codes(self):
        for code in ["BAD_REQUEST_ERROR", "CARD_EXPIRED", "INVALID_VPA", "ACCOUNT_CLOSED"]:
            cat, conf, _ = self.clf.classify(make_payment(error_code=code))
            assert cat == "terminal", f"{code} should be terminal, got {cat}"

    def test_suspicious_codes(self):
        for code in ["DUPLICATE_TRANSACTION", "FRAUD_SUSPECTED"]:
            cat, conf, _ = self.clf.classify(make_payment(error_code=code))
            assert cat == "suspicious", f"{code} should be suspicious, got {cat}"

    def test_unknown_code_defaults_recoverable(self):
        cat, conf, _ = self.clf.classify(make_payment(error_code="NEVER_SEEN_BEFORE"))
        assert cat == "recoverable"
        assert conf == 0.50  # lower confidence for unknown

    def test_all_error_codes_covered(self):
        """Every code in bank_error_codes.json maps to a valid category."""
        for code, mapping in self.clf.error_code_map.items():
            assert mapping["category"] in ["transient", "recoverable", "terminal", "suspicious"], \
                f"{code} has invalid category: {mapping['category']}"


# ── Recovery Agent Tests ──────────────────────────────────

class TestRecoveryAgent:
    def setup_method(self):
        self.audit, self._db_path = make_audit()
        self.agent = RecoveryAgent(audit_trail=self.audit)

    def teardown_method(self):
        os.unlink(self._db_path)

    def test_transient_retries(self):
        strategy = self.agent.determine_strategy(make_payment(error_code="GATEWAY_ERROR"))
        assert strategy["action"] == "retry_payment"
        assert strategy["retry_delay_minutes"] is not None

    def test_recoverable_sends_link(self):
        strategy = self.agent.determine_strategy(make_payment(error_code="CARD_DECLINED"))
        assert strategy["action"] == "send_payment_link"
        assert strategy["alternative_method"] is not None

    def test_suspicious_always_escalates(self):
        strategy = self.agent.determine_strategy(make_payment(error_code="FRAUD_SUSPECTED"))
        assert strategy["action"] == "escalate_to_human"

    def test_max_retries_forces_escalation(self):
        payment = make_payment(error_code="GATEWAY_ERROR", retry_count=3)
        strategy = self.agent.determine_strategy(payment)
        assert strategy["action"] != "retry_payment"

    def test_guardrails_reject_invalid_action(self):
        strategy = {"action": "delete_account", "reasoning": "bad idea", "confidence": 0.9}
        fixed = self.agent._enforce_guardrails(strategy, make_payment(), "transient", 0)
        assert fixed["action"] == "escalate_to_human"
        assert "GUARDRAIL" in fixed["reasoning"]

    def test_guardrails_block_retry_at_max(self):
        strategy = {"action": "retry_payment", "reasoning": "try again", "confidence": 0.9}
        fixed = self.agent._enforce_guardrails(strategy, make_payment(), "transient", 3)
        assert fixed["action"] == "send_payment_link"

    def test_guardrails_force_escalate_suspicious(self):
        strategy = {"action": "retry_payment", "reasoning": "retry", "confidence": 0.9}
        fixed = self.agent._enforce_guardrails(strategy, make_payment(), "suspicious", 0)
        assert fixed["action"] == "escalate_to_human"

    def test_strategy_output_shape(self):
        strategy = self.agent.determine_strategy(make_payment())
        required_keys = {"action", "reasoning", "confidence", "urgency", "timestamp"}
        assert required_keys.issubset(set(strategy.keys()))

    def test_all_actions_in_allowed_list(self):
        """No strategy can produce an action outside ALLOWED_ACTIONS."""
        test_cases = [
            make_payment(error_code="GATEWAY_ERROR"),
            make_payment(error_code="CARD_DECLINED"),
            make_payment(error_code="FRAUD_SUSPECTED"),
            make_payment(error_code="ACCOUNT_CLOSED"),
            make_payment(error_code="GATEWAY_ERROR", retry_count=3),
        ]
        for payment in test_cases:
            strategy = self.agent.determine_strategy(payment)
            assert strategy["action"] in ALLOWED_ACTIONS, \
                f"Action {strategy['action']} not in ALLOWED_ACTIONS for {payment['error_code']}"


# ── RetryEngine Tests ─────────────────────────────────────

class TestRetryEngine:
    def setup_method(self):
        from src.retry_engine import RetryEngine
        self.audit, self._db_path = make_audit()
        self.engine = RetryEngine(audit_trail=self.audit)
        # Force mock client regardless of .env
        self.engine.rzp = MockRazorpayClient()

    def teardown_method(self):
        os.unlink(self._db_path)

    def test_retry_action(self):
        result = self.engine.execute_strategy(
            make_payment(), {"action": "retry_payment", "message_tone": "empathetic"}
        )
        assert result["success"] is True
        assert result["outcome"] == "retry_initiated"
        assert "order_id" in result

    def test_payment_link_action(self):
        result = self.engine.execute_strategy(
            make_payment(), {"action": "send_payment_link", "message_tone": "empathetic", "alternative_method": "upi"}
        )
        assert result["success"] is True
        assert result["outcome"] == "link_sent"
        assert "link_url" in result

    def test_paylater_action(self):
        result = self.engine.execute_strategy(
            make_payment(), {"action": "offer_razorpay_paylater", "message_tone": "empathetic"}
        )
        assert result["success"] is True
        assert result["outcome"] == "link_sent"

    def test_negotiate_retention_action(self):
        result = self.engine.execute_strategy(
            make_payment(), {"action": "negotiate_retention", "message_tone": "empathetic"}
        )
        assert result["success"] is True
        assert result["outcome"] == "link_sent"

    def test_escalation_action(self):
        result = self.engine.execute_strategy(
            make_payment(), {"action": "escalate_to_human", "message_tone": "empathetic", "urgency": "high"}
        )
        assert result["success"] is True
        assert result["outcome"] == "escalated"
        assert self.engine.get_human_queue()

    def test_no_action(self):
        result = self.engine.execute_strategy(
            make_payment(), {"action": "no_action"}
        )
        assert result["success"] is True
        assert result["outcome"] == "no_action"

    def test_unknown_action_fails(self):
        result = self.engine.execute_strategy(
            make_payment(), {"action": "launch_missiles"}
        )
        assert result["success"] is False


# ── Message Generator Tests ───────────────────────────────

class TestMessageGenerator:
    def setup_method(self):
        self.gen = MessageGenerator()

    def test_english_message(self):
        msg = self.gen.generate_message(
            make_payment(language="english"),
            {"action": "retry_payment", "message_tone": "empathetic"}
        )
        assert msg["language"] == "english"
        assert "1,500" in msg["message"]
        assert "Rahul" in msg["message"]

    def test_hinglish_message(self):
        msg = self.gen.generate_message(
            make_payment(language="hinglish"),
            {"action": "send_payment_link", "message_tone": "empathetic"}
        )
        assert msg["language"] == "hinglish"
        assert "Rahul" in msg["message"]

    def test_hindi_message(self):
        msg = self.gen.generate_message(
            make_payment(language="hindi"),
            {"action": "retry_payment", "message_tone": "empathetic"}
        )
        assert msg["language"] == "hindi"

    def test_all_actions_have_templates(self):
        actions = ["retry_payment", "send_payment_link", "offer_razorpay_paylater",
                    "negotiate_retention", "escalate_to_human"]
        for action in actions:
            msg = self.gen.generate_message(
                make_payment(), {"action": action, "message_tone": "empathetic"}
            )
            assert len(msg["message"]) > 0, f"Empty message for action: {action}"

    def test_all_tones_work(self):
        for tone in ["empathetic", "reminder", "urgent"]:
            msg = self.gen.generate_message(
                make_payment(), {"action": "retry_payment", "message_tone": tone}
            )
            assert len(msg["message"]) > 0, f"Empty message for tone: {tone}"

    def test_unknown_language_falls_back_to_english(self):
        msg = self.gen.generate_message(
            make_payment(language="telugu"),
            {"action": "retry_payment", "message_tone": "empathetic"}
        )
        assert msg["language"] == "english"


# ── Audit Trail Tests ─────────────────────────────────────

class TestAuditTrail:
    def setup_method(self):
        self.audit, self._db_path = make_audit()

    def teardown_method(self):
        os.unlink(self._db_path)

    def test_log_and_retrieve(self):
        entry_id = self.audit.log_action(
            payment_id="pay_test_001",
            action="retry_payment",
            agent_reasoning="Transient failure, retrying",
            confidence=0.90,
            amount=1500,
            error_code="GATEWAY_ERROR",
        )
        entries = self.audit.get_entries_by_payment("pay_test_001")
        assert len(entries) == 1
        assert entries[0]["action"] == "retry_payment"
        assert entries[0]["confidence"] == 0.90

    def test_update_outcome(self):
        entry_id = self.audit.log_action(
            payment_id="pay_test_002", action="retry_payment",
            agent_reasoning="test", confidence=0.9
        )
        self.audit.update_outcome(entry_id, "success", recovery_amount=1500)
        entries = self.audit.get_entries_by_payment("pay_test_002")
        assert entries[0]["outcome"] == "success"
        assert entries[0]["recovery_amount"] == 1500

    def test_recovery_summary(self):
        self.audit.log_action(payment_id="p1", action="retry_payment",
                              agent_reasoning="test", confidence=0.9, amount=1000)
        summary = self.audit.get_recovery_summary()
        assert "total_failed_amount" in summary
        assert "recovery_rate" in summary


# ── Mock Razorpay Client Tests ────────────────────────────

class TestMockRazorpayClient:
    def setup_method(self):
        self.client = MockRazorpayClient()

    def test_create_order(self):
        order = self.client.create_order(amount_paise=150000)
        assert order["id"].startswith("order_test_mock_")
        assert order["amount"] == 150000
        assert order["status"] == "created"

    def test_create_payment_link(self):
        link = self.client.create_payment_link(
            amount_paise=150000, customer_name="Test",
            customer_email="t@t.com", customer_phone="+91999"
        )
        assert link["id"].startswith("plink_test_mock_")
        assert "rzp.io" in link["short_url"]

    def test_ids_are_unique(self):
        o1 = self.client.create_order(amount_paise=100)
        o2 = self.client.create_order(amount_paise=100)
        assert o1["id"] != o2["id"]


# ── Escalation Manager Tests ─────────────────────────────

class TestEscalationManager:
    def setup_method(self):
        self.audit, self._db_path = make_audit()
        self.esc = EscalationManager(audit_trail=self.audit)

    def teardown_method(self):
        os.unlink(self._db_path)

    def test_no_history_allows_proceed(self):
        should_stop, reason = self.esc.should_stop(make_payment())
        assert should_stop is False

    def test_already_escalated_stops(self):
        self.audit.log_action(
            payment_id="pay_test_gateway_error", action="escalate_to_human",
            agent_reasoning="test", confidence=0.9
        )
        should_stop, reason = self.esc.should_stop(make_payment())
        assert should_stop is True
        assert "human" in reason.lower()

    def test_recovered_payment_stops(self):
        entry_id = self.audit.log_action(
            payment_id="pay_test_gateway_error", action="retry_payment",
            agent_reasoning="test", confidence=0.9
        )
        self.audit.update_outcome(entry_id, "success", recovery_amount=1500)
        should_stop, reason = self.esc.should_stop(make_payment())
        assert should_stop is True

    def test_max_touchpoints_stops(self):
        for i in range(3):
            self.audit.log_action(
                payment_id="pay_test_gateway_error", action="retry_payment",
                agent_reasoning=f"attempt {i}", confidence=0.9
            )
        should_stop, reason = self.esc.should_stop(make_payment())
        assert should_stop is True
        assert "touchpoint" in reason.lower()


# ── Integration: End-to-End Pipeline ─────────────────────

class TestEndToEnd:
    """Tests the full pipeline: classify -> strategize -> execute."""

    def setup_method(self):
        from src.retry_engine import RetryEngine
        self.audit, self._db_path = make_audit()
        self.agent = RecoveryAgent(audit_trail=self.audit)
        self.engine = RetryEngine(audit_trail=self.audit)
        self.engine.rzp = MockRazorpayClient()

    def teardown_method(self):
        os.unlink(self._db_path)

    def test_transient_pipeline(self):
        payment = make_payment(error_code="GATEWAY_ERROR")
        strategy = self.agent.determine_strategy(payment)
        result = self.engine.execute_strategy(payment, strategy)
        assert strategy["action"] == "retry_payment"
        assert result["success"] is True
        assert "message" in result

    def test_recoverable_pipeline(self):
        payment = make_payment(error_code="INSUFFICIENT_FUNDS")
        strategy = self.agent.determine_strategy(payment)
        result = self.engine.execute_strategy(payment, strategy)
        assert strategy["action"] == "send_payment_link"
        assert result["success"] is True

    def test_suspicious_pipeline(self):
        payment = make_payment(error_code="FRAUD_SUSPECTED")
        strategy = self.agent.determine_strategy(payment)
        result = self.engine.execute_strategy(payment, strategy)
        assert strategy["action"] == "escalate_to_human"
        assert result["success"] is True
        assert result["outcome"] == "escalated"

    def test_hinglish_end_to_end(self):
        payment = make_payment(error_code="CARD_DECLINED", language="hinglish")
        strategy = self.agent.determine_strategy(payment)
        result = self.engine.execute_strategy(payment, strategy)
        assert result["success"] is True
        assert result["message_language"] == "hinglish"

    def test_audit_trail_populated(self):
        payment = make_payment(error_code="GATEWAY_ERROR")
        self.agent.determine_strategy(payment)
        entries = self.audit.get_entries_by_payment(payment["payment_id"])
        assert len(entries) >= 1
        assert entries[0]["action"] in ALLOWED_ACTIONS
