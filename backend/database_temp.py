from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models_temp import Base  # Use temporary models without pgvector
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://rinkut@localhost:5432/financial_advisor_agent")

logger.info(f"Initializing database connection to: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'localhost'}")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_tables():
    """Create all tables"""
    logger.info("Creating database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        raise

def get_db():
    """Dependency to get database session"""
    logger.debug("Creating new database session")
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        db.rollback()
        raise
    finally:
        logger.debug("Closing database session")
        db.close()
