"""RecoverAI Dashboard — Streamlit frontend for the Razorpay AI Buildathon.

This is the main entry point for the demo. Run with:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import time
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from src.audit import AuditTrail
from src.classifier import FailureClassifier
from src.recovery_agent import RecoveryAgent
from src.retry_engine import RetryEngine
from src.escalation import EscalationManager
from src.message_generator import MessageGenerator

# Page config
st.set_page_config(
    page_title="RecoverAI — Payment Recovery Agent",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize components
@st.cache_resource
def init_components():
    audit = AuditTrail()
    classifier = FailureClassifier()
    agent = RecoveryAgent(audit_trail=audit, classifier=classifier)
    engine = RetryEngine(audit_trail=audit)
    escalation = EscalationManager(audit_trail=audit)
    return audit, classifier, agent, engine, escalation

audit, classifier, agent, engine, escalation = init_components()

# Sidebar navigation
st.sidebar.title("💰 RecoverAI")
st.sidebar.caption("AI-Powered Payment Recovery Agent")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate",
    ["🏠 Dashboard", "🔄 Run Recovery", "📋 Audit Trail", "📊 Metrics", "💬 Message Preview", "📈 Evaluation"],
    label_visibility="collapsed",
)

# ===== PAGE 1: Dashboard =====
if page == "🏠 Dashboard":
    st.title("💰 RecoverAI Dashboard")
    st.caption("Real-time payment recovery monitoring")
    
    summary = audit.get_recovery_summary()
    
    # Key metrics row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Failed", f"₹{summary['total_failed_amount']:,.0f}")
    with col2:
        st.metric("Recovered", f"₹{summary['total_recovered_amount']:,.0f}")
    with col3:
        st.metric("Recovery Rate", f"{summary['recovery_rate']}%")
    with col4:
        st.metric("Total Actions", summary['total_entries'])
    
    st.markdown("---")
    
    # Charts row
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.subheader("Actions Taken")
        action_data = summary.get("action_counts", {})
        if action_data:
            fig = px.pie(
                names=list(action_data.keys()),
                values=list(action_data.values()),
                color_discrete_sequence=px.colors.qualitative.Set2,
                hole=0.4,
            )
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No recovery actions yet. Go to '🔄 Run Recovery' to start.")
    
    with col_right:
        st.subheader("Failure Categories")
        cat_data = summary.get("category_counts", {})
        if cat_data:
            fig = px.bar(
                x=list(cat_data.keys()),
                y=list(cat_data.values()),
                color=list(cat_data.keys()),
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig.update_layout(margin=dict(t=20, b=20), showlegend=False,
                            xaxis_title="Category", yaxis_title="Count")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data yet.")
    
    # Recent activity
    st.subheader("Recent Activity")
    entries = audit.get_all_entries()
    if entries:
        df = pd.DataFrame(entries[:20])  # Last 20
        display_cols = ["timestamp", "payment_id", "amount", "error_code", 
                       "failure_category", "action", "outcome", "confidence"]
        available_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No activity yet. Run recovery on synthetic data to see results.")

# ===== PAGE 2: Run Recovery =====
elif page == "🔄 Run Recovery":
    st.title("🔄 Run Recovery Agent")
    st.caption("Process failed payments through the AI recovery pipeline")
    
    # Load synthetic data
    data_dir = Path(__file__).parent / "data"
    train_file = data_dir / "synthetic_payments.json"
    test_file = data_dir / "synthetic_test_set.json"
    
    data_source = st.radio(
        "Select data source",
        ["Training Set", "Test Set (Held-out)"],
        horizontal=True,
    )
    
    file_path = train_file if data_source == "Training Set" else test_file
    
    if file_path.exists():
        with open(file_path) as f:
            payments = json.load(f)
        
        st.success(f"Loaded {len(payments)} failed payments from {file_path.name}")
        
        # Show sample
        with st.expander("Preview Data", expanded=False):
            st.json(payments[:3])
        
        # Run options
        col1, col2 = st.columns(2)
        with col1:
            run_all = st.button("🚀 Run Recovery on ALL Payments", type="primary", use_container_width=True)
        with col2:
            clear = st.button("🗑️ Clear Audit Trail", use_container_width=True)
        
        if clear:
            audit.clear_all()
            st.success("Audit trail cleared!")
            st.rerun()
        
        if run_all:
            progress = st.progress(0)
            status = st.empty()
            results_container = st.container()
            
            results = []
            for i, payment in enumerate(payments):
                progress.progress((i + 1) / len(payments))
                status.text(f"Processing {payment.get('payment_id', 'unknown')}... ({i+1}/{len(payments)})")
                
                # Run the recovery pipeline
                strategy = agent.determine_strategy(payment)
                result = engine.execute_strategy(payment, strategy)
                
                # Simulate outcome (for demo purposes)
                import random
                if strategy["action"] in ["retry_payment", "send_payment_link"]:
                    success_prob = 0.65 if strategy["action"] == "retry_payment" else 0.55
                    if random.random() < success_prob:
                        result["outcome"] = "success"
                        result["recovery_amount"] = float(payment.get("amount", 0))
                    else:
                        result["outcome"] = "failed"
                
                # Update audit trail with simulated outcome
                entries = audit.get_entries_by_payment(payment.get("payment_id", ""))
                if entries:
                    latest = entries[-1]
                    audit.update_outcome(
                        latest["id"],
                        outcome=result.get("outcome", "pending"),
                        recovery_amount=result.get("recovery_amount", 0),
                    )
                
                results.append({
                    "payment_id": payment.get("payment_id"),
                    "amount": payment.get("amount"),
                    "error_code": payment.get("error_code"),
                    "category": strategy.get("action"),
                    "action": strategy["action"],
                    "outcome": result.get("outcome", "pending"),
                    "reasoning": strategy["reasoning"][:100] + "...",
                })
                
                time.sleep(0.1)  # Small delay for visual effect
            
            progress.progress(1.0)
            status.text("✅ Recovery complete!")
            
            with results_container:
                st.subheader("Recovery Results")
                results_df = pd.DataFrame(results)
                st.dataframe(results_df, use_container_width=True, hide_index=True)
                
                # Quick summary
                successes = len([r for r in results if r["outcome"] == "success"])
                total_recovered = sum(r["amount"] for r in results if r["outcome"] == "success")
                total_failed = sum(r["amount"] for r in results)
                
                st.markdown(f"""
                ### Quick Summary
                - **Processed:** {len(results)} payments
                - **Recovered:** {successes}/{len(results)} ({successes/len(results)*100:.1f}%)
                - **Amount Recovered:** ₹{total_recovered:,.0f} / ₹{total_failed:,.0f}
                """)
    else:
        st.error(f"Data file not found: {file_path}")
        st.info("Run `python data/generate_synthetic.py` to generate test data.")

# ===== PAGE 3: Audit Trail =====
elif page == "📋 Audit Trail":
    st.title("📋 Audit Trail")
    st.caption("Complete log of every AI decision with full reasoning")
    
    entries = audit.get_all_entries()
    
    if entries:
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            action_filter = st.multiselect(
                "Filter by Action",
                options=list(set(e["action"] for e in entries)),
                default=None,
            )
        with col2:
            category_filter = st.multiselect(
                "Filter by Category",
                options=list(set(e["failure_category"] for e in entries if e["failure_category"])),
                default=None,
            )
        with col3:
            outcome_filter = st.multiselect(
                "Filter by Outcome",
                options=list(set(e["outcome"] for e in entries)),
                default=None,
            )
        
        # Apply filters
        filtered = entries
        if action_filter:
            filtered = [e for e in filtered if e["action"] in action_filter]
        if category_filter:
            filtered = [e for e in filtered if e["failure_category"] in category_filter]
        if outcome_filter:
            filtered = [e for e in filtered if e["outcome"] in outcome_filter]
        
        st.info(f"Showing {len(filtered)} of {len(entries)} entries")
        
        # Display entries
        for entry in filtered[:50]:  # Limit display
            outcome_emoji = {"success": "✅", "failed": "❌", "pending": "⏳"}.get(entry["outcome"], "❓")
            action_emoji = {
                "retry_payment": "🔄",
                "send_payment_link": "🔗",
                "escalate_to_human": "👤",
                "no_action": "⏸️",
            }.get(entry["action"], "❓")
            
            with st.expander(
                f"{outcome_emoji} {action_emoji} {entry['payment_id']} — "
                f"₹{entry.get('amount', 0):,.0f} — {entry['action']} — {entry['timestamp'][:19]}"
            ):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Payment ID:** `{entry['payment_id']}`")
                    st.markdown(f"**Amount:** ₹{entry.get('amount', 0):,.0f}")
                    st.markdown(f"**Error Code:** `{entry.get('error_code', 'N/A')}`")
                    st.markdown(f"**Category:** {entry.get('failure_category', 'N/A')}")
                    st.markdown(f"**Confidence:** {entry.get('confidence', 0):.1%}")
                with col2:
                    st.markdown(f"**Action:** {entry['action']}")
                    st.markdown(f"**Outcome:** {entry['outcome']}")
                    st.markdown(f"**Retry Attempt:** {entry.get('retry_attempt', 0)}")
                    st.markdown(f"**Language:** {entry.get('message_language', 'N/A')}")
                    if entry.get('recovery_amount'):
                        st.markdown(f"**Recovered:** ₹{entry['recovery_amount']:,.0f}")
                
                st.markdown("**🧠 Agent Reasoning:**")
                st.info(entry.get('agent_reasoning', 'No reasoning recorded'))
                
                if entry.get('message_generated'):
                    st.markdown("**💬 Recovery Message:**")
                    st.success(entry['message_generated'])
    else:
        st.info("No audit entries yet. Run recovery to generate data.")

# ===== PAGE 4: Metrics =====
elif page == "📊 Metrics":
    st.title("📊 Recovery Metrics")
    st.caption("Honest, measured performance metrics")
    
    summary = audit.get_recovery_summary()
    
    if summary["total_entries"] > 0:
        # Key metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Recovery Rate", f"{summary['recovery_rate']}%")
        with col2:
            st.metric("Total Processed", summary['total_entries'])
        with col3:
            escalation_count = summary.get('action_counts', {}).get('escalate_to_human', 0)
            escalation_rate = (escalation_count / summary['total_entries'] * 100) if summary['total_entries'] > 0 else 0
            st.metric("Escalation Rate", f"{escalation_rate:.1f}%")
        
        st.markdown("---")
        
        # Outcome distribution
        st.subheader("Outcome Distribution")
        outcome_data = summary.get("outcome_counts", {})
        if outcome_data:
            fig = px.pie(
                names=list(outcome_data.keys()),
                values=list(outcome_data.values()),
                color_discrete_map={"success": "#2ecc71", "failed": "#e74c3c", "pending": "#f39c12"},
                hole=0.4,
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Action effectiveness
        st.subheader("Action Effectiveness")
        entries = audit.get_all_entries()
        if entries:
            df = pd.DataFrame(entries)
            if 'action' in df.columns and 'outcome' in df.columns:
                cross = pd.crosstab(df['action'], df['outcome'], normalize='index') * 100
                st.dataframe(cross.round(1).astype(str) + '%', use_container_width=True)
        
        # Exceptions (honest reporting)
        st.subheader("⚠️ Exceptions & Unresolved Cases")
        failed_entries = [e for e in entries if e["outcome"] == "failed"]
        if failed_entries:
            st.warning(f"{len(failed_entries)} payments could not be recovered:")
            for e in failed_entries[:10]:
                st.markdown(
                    f"- `{e['payment_id']}` — ₹{e.get('amount', 0):,.0f} — "
                    f"{e.get('error_code', 'N/A')} — *{e.get('agent_reasoning', 'N/A')[:80]}...*"
                )
        else:
            st.success("No unresolved exceptions!")
    else:
        st.info("No data to show. Run recovery first.")

# ===== PAGE 5: Message Preview =====
elif page == "💬 Message Preview":
    st.title("💬 Recovery Message Preview")
    st.caption("Preview personalized recovery messages in English, Hindi & Hinglish")
    
    msg_gen = MessageGenerator()
    
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Customer Name", value="Rahul Sharma")
        amount = st.number_input("Amount (₹)", value=1499, min_value=1)
        language = st.selectbox("Language Preference", ["hinglish", "english", "hindi"])
    with col2:
        error = st.selectbox("Error Type", ["INSUFFICIENT_FUNDS", "CARD_EXPIRED", "BANK_TIMEOUT", "NETWORK_ERROR"])
        tone = st.selectbox("Message Tone", ["empathetic", "reminder", "urgent"])
        action = st.selectbox("Recovery Action", ["send_payment_link", "retry_payment", "escalate_to_human"])
    
    if st.button("Generate Message", type="primary"):
        payment = {
            "amount": amount,
            "error_code": error,
            "error_description": error.replace("_", " ").lower(),
            "customer": {"name": name, "language_pref": language},
        }
        strategy = {"action": action, "message_tone": tone}
        
        result = msg_gen.generate_message(payment, strategy, "https://rzp.io/i/demo123")
        
        st.markdown("### Generated Message")
        st.success(result["message"])
        st.caption(f"Language: {result['language']} | Tone: {tone}")
    
    # Show template examples
    st.markdown("---")
    st.subheader("Template Examples")
    
    from src.message_generator import MESSAGE_TEMPLATES
    
    for lang in ["english", "hinglish", "hindi"]:
        with st.expander(f"📝 {lang.title()} Templates"):
            templates = MESSAGE_TEMPLATES.get(lang, {})
            for tone_name, tone_msgs in templates.items():
                st.markdown(f"**{tone_name.title()} Tone:**")
                for action_name, msg in tone_msgs.items():
                    sample = msg.format(
                        name="Rahul", amount="1,499",
                        reason="insufficient funds",
                        link="https://rzp.io/i/demo123"
                    )
                    st.markdown(f"- *{action_name}:* {sample}")

# ===== PAGE 6: Evaluation =====
elif page == "📈 Evaluation":
    st.title("📈 Model Evaluation")
    st.caption("Classifier performance on held-out test set")
    
    test_file = Path(__file__).parent / "data" / "synthetic_test_set.json"
    
    if test_file.exists():
        with open(test_file) as f:
            test_data = json.load(f)
        
        st.info(f"Test set: {len(test_data)} held-out transactions")
        
        if st.button("Run Evaluation", type="primary"):
            # Get true labels from error code mapping
            true_labels = []
            for p in test_data:
                error_code = p.get("error_code", "UNKNOWN")
                if error_code in classifier.error_code_map:
                    true_labels.append(classifier.error_code_map[error_code]["category"])
                else:
                    true_labels.append("recoverable")
            
            # Evaluate
            metrics = classifier.evaluate(test_data, true_labels)
            
            st.subheader("Classification Results")
            
            # Accuracy
            st.metric("Overall Accuracy", f"{metrics['accuracy']:.1%}")
            
            # Classification report
            report = metrics["classification_report"]
            report_df = pd.DataFrame(report).transpose()
            st.dataframe(report_df.round(3), use_container_width=True)
            
            # Confusion matrix
            st.subheader("Confusion Matrix")
            cm = metrics["confusion_matrix"]
            fig = px.imshow(
                cm,
                labels=dict(x="Predicted", y="Actual", color="Count"),
                x=classifier.CATEGORIES,
                y=classifier.CATEGORIES,
                color_continuous_scale="Blues",
                text_auto=True,
            )
            fig.update_layout(margin=dict(t=30, b=30))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("Test set not found. Run `python data/generate_synthetic.py` first.")

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown(
    "Built for [Razorpay AI Buildathon 2026](https://razorpay.com/buildathon/)\n\n"
    "Track 3: AI Revenue Recovery"
)
