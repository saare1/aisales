import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    # App settings
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "default-secret-key")
    
    # Database settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sales_agent.db")
    
    # OpenAI settings
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    
    # Email settings
    SENDGRID_API_KEY: Optional[str] = os.getenv("SENDGRID_API_KEY")
    EMAIL_FROM: Optional[str] = os.getenv("EMAIL_FROM")
    EMAIL_NAME: Optional[str] = os.getenv("EMAIL_NAME", "AI Sales Closer")
    
    # SMS settings
    TWILIO_ACCOUNT_SID: Optional[str] = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN: Optional[str] = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER: Optional[str] = os.getenv("TWILIO_PHONE_NUMBER")
    
    # Calendar settings
    CALENDLY_API_KEY: Optional[str] = os.getenv("CALENDLY_API_KEY")
    MEETING_LINK: Optional[str] = os.getenv("MEETING_LINK")
    
    # Agent settings
    MAX_FOLLOWUPS: int = int(os.getenv("MAX_FOLLOWUPS", "3"))
    FOLLOWUP_INTERVAL_HOURS: int = int(os.getenv("FOLLOWUP_INTERVAL_HOURS", "24"))
    MAX_CONCURRENT_LEADS: int = int(os.getenv("MAX_CONCURRENT_LEADS", "10"))


# Create global settings object
settings = Settings() 