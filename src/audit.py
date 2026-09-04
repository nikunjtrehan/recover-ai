"""Audit Trail System — logs every AI decision with full reasoning.

Every action the RecoverAI agent takes is recorded here with:
- Timestamp
- Payment context
- Action taken
- AI reasoning (why this action was chosen)
- Confidence score
- Outcome (pending/success/failed)

This creates the complete audit trail that Razorpay judges explicitly require.
"""

import sqlite3
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path


class AuditTrail:
    """SQLite-backed audit trail for all recovery actions."""
    
    def __init__(self, db_path: str = "recover_ai.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize the database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                order_id TEXT,
                amount REAL,
                currency TEXT DEFAULT 'INR',
                error_code TEXT,
                failure_category TEXT,
                action TEXT NOT NULL,
                action_detail TEXT,
                agent_reasoning TEXT,
                confidence REAL,
                retry_attempt INTEGER DEFAULT 0,
                escalation_level TEXT,
                message_generated TEXT,
                message_language TEXT,
                outcome TEXT DEFAULT 'pending',
                outcome_detail TEXT,
                recovery_amount REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recovery_metrics (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                total_failed_amount REAL,
                total_recovered_amount REAL,
                recovery_rate REAL,
                total_transactions INTEGER,
                successful_recoveries INTEGER,
                failed_recoveries INTEGER,
                pending_recoveries INTEGER,
                avg_recovery_time_hours REAL,
                classification_accuracy REAL,
                precision_by_category TEXT,
                recall_by_category TEXT,
                exceptions TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def log_action(self, payment_id: str, action: str, agent_reasoning: str,
                   confidence: float, order_id: str = None, amount: float = None,
                   error_code: str = None, failure_category: str = None,
                   action_detail: str = None, retry_attempt: int = 0,
                   escalation_level: str = None, message_generated: str = None,
                   message_language: str = None) -> str:
        """Log a recovery action to the audit trail.
        
        Returns the audit log entry ID.
        """
        entry_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_log (
                id, timestamp, payment_id, order_id, amount, error_code,
                failure_category, action, action_detail, agent_reasoning,
                confidence, retry_attempt, escalation_level,
                message_generated, message_language, outcome, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (entry_id, now, payment_id, order_id, amount, error_code,
               failure_category, action, action_detail, agent_reasoning,
               confidence, retry_attempt, escalation_level,
               message_generated, message_language, now))
        conn.commit()
        conn.close()
        
        return entry_id
    
    def update_outcome(self, entry_id: str, outcome: str,
                       outcome_detail: str = None, recovery_amount: float = 0):
        """Update the outcome of a recovery action."""
        now = datetime.utcnow().isoformat() + "Z"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE audit_log 
            SET outcome = ?, outcome_detail = ?, recovery_amount = ?, updated_at = ?
            WHERE id = ?
        """, (outcome, outcome_detail, recovery_amount, now, entry_id))
        conn.commit()
        conn.close()
    
    def get_all_entries(self) -> List[Dict[str, Any]]:
        """Get all audit log entries."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log ORDER BY timestamp DESC")
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    
    def get_entries_by_payment(self, payment_id: str) -> List[Dict[str, Any]]:
        """Get all audit entries for a specific payment."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM audit_log WHERE payment_id = ? ORDER BY timestamp",
            (payment_id,)
        )
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    
    def get_recovery_summary(self) -> Dict[str, Any]:
        """Get summary statistics for the dashboard."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total failed amount
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM audit_log WHERE action != 'no_action'")
        total_failed = cursor.fetchone()[0]
        
        # Total recovered
        cursor.execute("SELECT COALESCE(SUM(recovery_amount), 0) FROM audit_log WHERE outcome = 'success'")
        total_recovered = cursor.fetchone()[0]
        
        # Counts by outcome
        cursor.execute("SELECT outcome, COUNT(*) FROM audit_log GROUP BY outcome")
        outcome_counts = dict(cursor.fetchall())
        
        # Counts by action
        cursor.execute("SELECT action, COUNT(*) FROM audit_log GROUP BY action")
        action_counts = dict(cursor.fetchall())
        
        # Counts by failure category
        cursor.execute("SELECT failure_category, COUNT(*) FROM audit_log GROUP BY failure_category")
        category_counts = dict(cursor.fetchall())
        
        conn.close()
        
        recovery_rate = (total_recovered / total_failed * 100) if total_failed > 0 else 0
        
        return {
            "total_failed_amount": total_failed,
            "total_recovered_amount": total_recovered,
            "recovery_rate": round(recovery_rate, 2),
            "outcome_counts": outcome_counts,
            "action_counts": action_counts,
            "category_counts": category_counts,
            "total_entries": sum(outcome_counts.values()) if outcome_counts else 0,
        }
    
    def save_metrics_snapshot(self, run_id: str, metrics: Dict[str, Any]):
        """Save a metrics snapshot for a batch evaluation run."""
        entry_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO recovery_metrics (
                id, run_id, timestamp, total_failed_amount, total_recovered_amount,
                recovery_rate, total_transactions, successful_recoveries,
                failed_recoveries, pending_recoveries, avg_recovery_time_hours,
                classification_accuracy, precision_by_category, recall_by_category,
                exceptions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry_id, run_id, now,
            metrics.get("total_failed_amount", 0),
            metrics.get("total_recovered_amount", 0),
            metrics.get("recovery_rate", 0),
            metrics.get("total_transactions", 0),
            metrics.get("successful_recoveries", 0),
            metrics.get("failed_recoveries", 0),
            metrics.get("pending_recoveries", 0),
            metrics.get("avg_recovery_time_hours", 0),
            metrics.get("classification_accuracy", 0),
            json.dumps(metrics.get("precision_by_category", {})),
            json.dumps(metrics.get("recall_by_category", {})),
            json.dumps(metrics.get("exceptions", []))
        ))
        conn.commit()
        conn.close()

    def clear_all(self):
        """Clear all audit entries. Use for testing only."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM audit_log")
        cursor.execute("DELETE FROM recovery_metrics")
        conn.commit()
        conn.close()
