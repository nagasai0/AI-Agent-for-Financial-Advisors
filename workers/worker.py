import os
import sys
import time
import logging
from datetime import datetime, timedelta
from rq import Worker, Queue
from rq.job import Job
import redis
from sqlalchemy.orm import Session

# Add parent directory to path to import backend modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from database import SessionLocal, engine
from models import User, Task, Account
from services.google import GoogleService
from services.hubspot import HubSpotService
from agent.runtime import AgentRuntime
from rag.ingest import RAGIngester
from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Redis connection
redis_conn = redis.from_url(settings.REDIS_URL)

# Initialize queues
poller_queue = Queue('pollers', connection=redis_conn)
task_queue = Queue('tasks', connection=redis_conn)

# Initialize services
google_service = GoogleService()
hubspot_service = HubSpotService()
agent_runtime = AgentRuntime()
rag_ingester = RAGIngester()

def get_db():
    """Get database session"""
    return SessionLocal()

def gmail_poller(user_id: str):
    """Poll Gmail for new messages and process them"""
    logger.info(f"Starting Gmail poller for user {user_id}")
    
    db = get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
        
        # Check if user has Google account
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'google'
        ).first()
        
        if not account:
            logger.info(f"User {user_id} has no Google account")
            return
        
        # Get messages from last 5 minutes (for frequent polling)
        since_date = datetime.utcnow() - timedelta(minutes=5)
        messages = google_service.gmail_list_since(user, since_date, db)
        
        if messages:
            logger.info(f"Found {len(messages)} new Gmail messages for user {user_id}")
            
            # Ingest new messages
            for msg in messages:
                content = f"Subject: {msg['subject']}\n\n{msg['body']}"
                rag_ingester.store_doc_chunks(
                    user=user,
                    source='gmail',
                    source_id=msg['id'],
                    content=content,
                    subject=msg['subject'],
                    contact_email=msg['from'],
                    db=db
                )
            
            # Check for waiting tasks that might be triggered by new emails
            waiting_tasks = db.query(Task).filter(
                Task.user_id == user.id,
                Task.status == "waiting"
            ).all()
            
            for task in waiting_tasks:
                # Check if this task is related to email replies
                if task.data and 'threadId' in task.data:
                    # Look for replies in the new messages
                    for msg in messages:
                        if msg.get('thread_id') == task.data['threadId']:
                            logger.info(f"Found reply for task {task.id}, resuming...")
                            # Resume the task
                            task_queue.enqueue(resume_task, task.id)
                            break
        
        logger.info(f"Gmail poller completed for user {user_id}")
        
    except Exception as e:
        logger.error(f"Gmail poller error for user {user_id}: {e}")
    finally:
        db.close()

def calendar_poller(user_id: str):
    """Poll Calendar for new events and process them"""
    logger.info(f"Starting Calendar poller for user {user_id}")
    
    db = get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
        
        # Check if user has Google account
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'google'
        ).first()
        
        if not account:
            logger.info(f"User {user_id} has no Google account")
            return
        
        # For now, we'll just log that we're checking calendar
        # In a full implementation, you'd fetch new calendar events
        # and apply ongoing instructions to them
        logger.info(f"Calendar poller completed for user {user_id}")
        
    except Exception as e:
        logger.error(f"Calendar poller error for user {user_id}: {e}")
    finally:
        db.close()

def hubspot_poller(user_id: str):
    """Poll HubSpot for new contacts/notes and process them"""
    logger.info(f"Starting HubSpot poller for user {user_id}")
    
    db = get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return
        
        # Check if user has HubSpot account
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'hubspot'
        ).first()
        
        if not account:
            logger.info(f"User {user_id} has no HubSpot account")
            return
        
        # Ingest incremental HubSpot data
        last_sync = datetime.utcnow() - timedelta(hours=1)  # Last hour
        new_items = rag_ingester.ingest_incremental_hubspot(user, last_sync, db)
        
        if new_items > 0:
            logger.info(f"Found {new_items} new HubSpot items for user {user_id}")
        
        logger.info(f"HubSpot poller completed for user {user_id}")
        
    except Exception as e:
        logger.error(f"HubSpot poller error for user {user_id}: {e}")
    finally:
        db.close()

def resume_task(task_id: str):
    """Resume a waiting task"""
    logger.info(f"Resuming task {task_id}")
    
    db = get_db()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.error(f"Task {task_id} not found")
            return
        
        if task.status != "waiting":
            logger.info(f"Task {task_id} is not in waiting status")
            return
        
        # Resume the task using agent runtime
        result = agent_runtime.resume_task(task, db)
        
        if result.get("success"):
            logger.info(f"Task {task_id} resumed successfully")
        else:
            logger.error(f"Task {task_id} resume failed: {result.get('error')}")
        
    except Exception as e:
        logger.error(f"Error resuming task {task_id}: {e}")
    finally:
        db.close()

def schedule_pollers():
    """Schedule poller jobs for all users"""
    logger.info("Scheduling pollers for all users")
    
    db = get_db()
    try:
        users = db.query(User).all()
        
        for user in users:
            # Schedule Gmail poller
            poller_queue.enqueue(gmail_poller, user.id)
            
            # Schedule Calendar poller
            poller_queue.enqueue(calendar_poller, user.id)
            
            # Schedule HubSpot poller
            poller_queue.enqueue(hubspot_poller, user.id)
        
        logger.info(f"Scheduled pollers for {len(users)} users")
        
    except Exception as e:
        logger.error(f"Error scheduling pollers: {e}")
    finally:
        db.close()

def main():
    """Main worker function"""
    logger.info("Starting Financial Advisor AI Agent Worker")
    
    # Create worker for poller queue
    poller_worker = Worker(['pollers'], connection=redis_conn)
    
    # Create worker for task queue
    task_worker = Worker(['tasks'], connection=redis_conn)
    
    # Schedule initial pollers
    schedule_pollers()
    
    # Schedule recurring pollers (every 2 minutes)
    def schedule_recurring():
        while True:
            time.sleep(120)  # 2 minutes
            schedule_pollers()
    
    import threading
    scheduler_thread = threading.Thread(target=schedule_recurring, daemon=True)
    scheduler_thread.start()
    
    logger.info("Workers started. Press Ctrl+C to stop.")
    
    try:
        # Start workers
        poller_worker.work()
        task_worker.work()
    except KeyboardInterrupt:
        logger.info("Shutting down workers...")
        poller_worker.shutdown()
        task_worker.shutdown()

if __name__ == "__main__":
    main()
