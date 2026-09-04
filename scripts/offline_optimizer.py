"""Offline Optimizer — Runs asynchronously, out of the hot path.

1. The hot-path (webhook) uses sub-5ms compiled rules + RandomForest.
2. The offline-path (this script) uses the LLM once a day to analyze
   historical logs and rewrite templates for higher conversion.
"""

import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


def run_offline_optimization():
    print("Starting Offline LLM Optimizer (Async Batch Job)")
    print("-" * 50)

    # 1. Read audit data from SQLite
    conn = sqlite3.connect(settings.db_path)
    c = conn.cursor()
    try:
        c.execute("""
            SELECT action, message_language, count(*) as volume
            FROM audit_log
            GROUP BY action, message_language
        """)
        stats = c.fetchall()
    except sqlite3.OperationalError:
        stats = "No data yet."
    conn.close()

    print(f"Daily volume metrics: {stats}")

    # 2. Call Gemini (free tier, once a day, NOT in hot path)
    if not settings.google_api_key:
        print("GOOGLE_API_KEY missing. Set it in .env to run optimization.")
        return

    print("Calling Gemini for template optimization... (Not in hot path!)")

    try:
        from google import genai  # ponytail: raw SDK, no langchain wrapper needed
        client = genai.Client(api_key=settings.google_api_key, http_options={"timeout": 30_000})

        prompt = f"""You are a conversion rate optimizer for Razorpay.
Here is yesterday's payment recovery volume: {stats}

Task: Write a high-converting Hinglish SMS template for the 'offer_razorpay_paylater' action.
Constraints:
1. Under 160 characters.
2. Must use behavioral economics (urgency + loyalty).
3. Do not include variables other than {{name}}, {{amount}}, and {{link}}.

Return ONLY valid JSON: {{"optimized_hinglish_template": "<message>"}}"""

        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
        )

        content = response.text.strip().strip('`').strip('json').strip()
        data = json.loads(content)

        # 3. Save for tomorrow's hot-path
        out_path = Path(settings.project_root) / "data" / "optimized_templates.json"
        out_path.parent.mkdir(exist_ok=True)

        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)

        print(f"\nOptimization complete.")
        print(f"New Template: {data.get('optimized_hinglish_template')}")
        print(f"Saved to {out_path.name} for tomorrow's hot-path execution.")

    except Exception as e:
        print(f"LLM Optimization failed: {e}")


if __name__ == "__main__":
    run_offline_optimization()
