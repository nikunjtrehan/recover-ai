"""RecoverAI Configuration — loads settings from .env file."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Razorpay
    razorpay_key_id: str = Field(default="rzp_test_placeholder", description="Razorpay test-mode key ID")
    razorpay_key_secret: str = Field(default="placeholder_secret", description="Razorpay test-mode key secret")
    
    # LLM
    llm_provider: str = Field(default="google", description="LLM provider: openai, anthropic, or google")
    use_llm_in_hot_path: bool = Field(default=False, description="If False, uses fast rules/templates. If True, calls LLM synchronously.")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    google_api_key: str = Field(default="", description="Google AI API key")
    
    # Server
    webhook_port: int = Field(default=8000, description="FastAPI webhook server port")
    streamlit_port: int = Field(default=8501, description="Streamlit dashboard port")
    
    # Recovery
    max_retries: int = Field(default=3, description="Maximum retry attempts per payment")
    cooldown_hours: int = Field(default=4, description="Minimum hours between retry attempts")
    
    # Database
    db_path: str = Field(default="recover_ai.db", description="SQLite database path")
    
    # Paths
    project_root: Path = Field(default_factory=lambda: Path(__file__).parent)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()

# Allowed actions — the agent CANNOT take any action outside this list
ALLOWED_ACTIONS = [
    "retry_payment",
    "send_payment_link", 
    "offer_razorpay_paylater",
    "negotiate_retention",
    "escalate_to_human",
    "no_action",
]

# Failure categories
FAILURE_CATEGORIES = {
    "transient": "Temporary failure — auto-retry with delay",
    "recoverable": "Payment can be recovered with alternative method",
    "terminal": "Permanent failure — needs human intervention",
    "suspicious": "Potentially fraudulent — flag for review",
}

# Escalation chain (compliant escalation order)
ESCALATION_CHAIN = ["retry_payment", "send_payment_link", "offer_razorpay_paylater", "escalate_to_human"]
