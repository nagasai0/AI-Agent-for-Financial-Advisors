import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # App
    APP_SECRET: str = os.getenv("APP_SECRET", "dev-secret-key")
    APP_URL: str = os.getenv("APP_URL", "https://learn-jump.onrender.com")
    
    # Base URL for OAuth redirects (can be overridden for different environments)
    OAUTH_REDIRECT_BASE: str = os.getenv("OAUTH_REDIRECT_BASE", "https://learn-jump.onrender.com")
    
    # Google AI
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+psycopg2://rinkut@localhost:5432/financial_advisor_agent")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", f"{os.getenv('OAUTH_REDIRECT_BASE', 'https://learn-jump.onrender.com')}/auth/google/callback")
    GOOGLE_SCOPES: str = os.getenv("GOOGLE_SCOPES", "openid email profile https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar")
    GOOGLE_PROJECT_ID: str = os.getenv("GOOGLE_PROJECT_ID", "")
    
    # HubSpot OAuth
    HUBSPOT_CLIENT_ID: str = os.getenv("HUBSPOT_CLIENT_ID", "")
    HUBSPOT_CLIENT_SECRET: str = os.getenv("HUBSPOT_CLIENT_SECRET", "")
    HUBSPOT_REDIRECT_URI: str = os.getenv("HUBSPOT_REDIRECT_URI", f"{os.getenv('OAUTH_REDIRECT_BASE', 'https://learn-jump.onrender.com')}/auth/hubspot/callback")
    HUBSPOT_SCOPES: str = os.getenv("HUBSPOT_SCOPES", "crm.objects.companies.read crm.objects.contacts.read crm.objects.contacts.write crm.objects.deals.read oauth")

settings = Settings()
