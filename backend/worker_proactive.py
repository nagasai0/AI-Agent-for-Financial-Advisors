"""
Background worker for processing webhook events and polling for changes
Runs proactive agent logic on incoming events
"""
import asyncio
import time
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database_temp import SessionLocal
from models_temp import WebhookEvent, User, WebhookSubscription, SyncState
from agent.proactive import proactive_agent
from services.webhooks import WebhookHandler
from services.google import GoogleService
from services.hubspot import HubSpotService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Worker configuration
POLL_INTERVAL_SECONDS = 60  # Check for new events every 60 seconds
PROCESS_BATCH_SIZE = 10  # Process 10 events at a time


class ProactiveWorker:
    """Background worker for proactive monitoring and event processing"""
    
    def __init__(self):
        self.webhook_handler = WebhookHandler()
        self.google_service = GoogleService()
        self.hubspot_service = HubSpotService()
        self.running = False
        logger.info("ProactiveWorker initialized")
    
    def start(self):
        """Start the background worker"""
        self.running = True
        logger.info("=" * 80)
        logger.info("PROACTIVE WORKER STARTED - Polling every 60 seconds")
        logger.info("=" * 80)
        
        iteration = 0
        while self.running:
            try:
                iteration += 1
                logger.info(f"[Worker Iteration {iteration}] Starting worker cycle...")
                
                # Process pending webhook events
                self._process_webhook_events()
                
                # Run polling for services without webhooks
                self._poll_for_changes()
                
                logger.info(f"[Worker Iteration {iteration}] Cycle complete. Sleeping for {POLL_INTERVAL_SECONDS} seconds...")
                
                # Sleep before next iteration
                time.sleep(POLL_INTERVAL_SECONDS)
                
            except KeyboardInterrupt:
                logger.info("Worker interrupted by user")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(POLL_INTERVAL_SECONDS)
    
    def stop(self):
        """Stop the background worker"""
        self.running = False
        logger.info("ProactiveWorker stopped")
    
    def _process_webhook_events(self):
        """Process unprocessed webhook events"""
        db = SessionLocal()
        try:
            # Get unprocessed events
            events = self.webhook_handler.get_unprocessed_events(db, limit=PROCESS_BATCH_SIZE)
            
            if not events:
                logger.debug("[Webhook Processing] No unprocessed webhook events")
                return
            
            logger.info(f"[Webhook Processing] ⚡ Processing {len(events)} webhook events")
            
            for event in events:
                try:
                    # Process event with proactive agent
                    logger.info(f"[Webhook Processing] 🔄 Processing event {event.id} (Provider: {event.provider}, Type: {event.event_type})")
                    
                    # Run async processing
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        proactive_agent.process_webhook_event(event, db)
                    )
                    loop.close()
                    
                    # Mark as processed
                    error = result.get('error') if not result.get('should_act') else None
                    self.webhook_handler.mark_event_processed(event.id, db, error=error)
                    
                    if result.get('should_act'):
                        logger.info(f"[Webhook Processing] ✅ Event {event.id} triggered actions: {len(result.get('actions_taken', []))} tools used")
                    else:
                        logger.info(f"[Webhook Processing] ⏭️  Event {event.id} did not require action")
                    
                except Exception as e:
                    logger.error(f"[Webhook Processing] ❌ Error processing event {event.id}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    self.webhook_handler.mark_event_processed(event.id, db, error=str(e))
            
            logger.info(f"Finished processing {len(events)} events")
            
        except Exception as e:
            logger.error(f"Error in _process_webhook_events: {e}")
        finally:
            db.close()
    
    def _poll_for_changes(self):
        """Poll for changes in Gmail, Calendar, and HubSpot (for users without webhooks)"""
        db = SessionLocal()
        try:
            # Get all users
            users = db.query(User).all()
            logger.info(f"[Polling] Found {len(users)} users to check")
            
            for user in users:
                try:
                    logger.info(f"[Polling] Checking user {user.id} ({user.email})...")
                    # Check if user has active webhooks, if not, poll for changes
                    self._poll_user_gmail(user, db)
                    self._poll_user_calendar(user, db)
                    
                except Exception as e:
                    logger.error(f"Error polling for user {user.id}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            logger.info(f"[Polling] Completed polling for all {len(users)} users")
            
        except Exception as e:
            logger.error(f"Error in _poll_for_changes: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            db.close()
    
    def _poll_user_gmail(self, user: User, db: Session):
        """Poll Gmail for new messages (if no webhook is active)"""
        try:
            # Check if there's an active webhook
            has_webhook = db.query(WebhookSubscription).filter(
                WebhookSubscription.user_id == user.id,
                WebhookSubscription.provider == 'gmail',
                WebhookSubscription.is_active == True
            ).first()
            
            if has_webhook:
                logger.debug(f"User {user.id} has active Gmail webhook, skipping poll")
                return
            
            # Get last sync state
            sync_state = db.query(SyncState).filter(
                SyncState.user_id == user.id,
                SyncState.provider == 'gmail',
                SyncState.resource_type == 'emails'
            ).first()
            
            # Only poll if last sync was more than 1 minute ago
            if sync_state and sync_state.last_sync_at:
                # Make datetime timezone-aware to match database
                now_utc = datetime.utcnow().replace(tzinfo=sync_state.last_sync_at.tzinfo) if sync_state.last_sync_at.tzinfo else datetime.utcnow()
                time_since_sync = now_utc - sync_state.last_sync_at
                if time_since_sync.total_seconds() < 60:  # 1 minute
                    return
            
            logger.info(f"Polling Gmail for user {user.id}")
            
            # Use Gmail API to check for new messages
            credentials = self.google_service.get_credentials(user, db)
            if not credentials:
                return
            
            from googleapiclient.discovery import build
            service = build('gmail', 'v1', credentials=credentials)
            
            # Get messages from last 10 minutes
            import time as time_module
            ten_min_ago = int(time_module.time()) - 600
            
            results = service.users().messages().list(
                userId='me',
                q=f'after:{ten_min_ago}',
                maxResults=5
            ).execute()
            
            messages = results.get('messages', [])
            
            if messages:
                logger.info(f"[Gmail Poll] ✓ Found {len(messages)} new messages for user {user.id}")
                
                # Fetch details for each message
                email_details = []
                for msg in messages[:5]:  # Limit to 5 most recent
                    try:
                        msg_data = service.users().messages().get(
                            userId='me',
                            id=msg['id'],
                            format='metadata',
                            metadataHeaders=['From', 'To', 'Subject', 'Date']
                        ).execute()
                        
                        headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
                        
                        email_details.append({
                            'id': msg['id'],
                            'from': headers.get('From', ''),
                            'to': headers.get('To', ''),
                            'subject': headers.get('Subject', ''),
                            'date': headers.get('Date', ''),
                            'snippet': msg_data.get('snippet', '')
                        })
                    except Exception as e:
                        logger.error(f"Error fetching email details for {msg['id']}: {e}")
                
                # Create a webhook event for processing with email details
                event = WebhookEvent(
                    user_id=user.id,
                    provider='gmail',
                    event_type='mailbox_update_poll',
                    resource_id=None,
                    payload={
                        'source': 'polling',
                        'message_count': len(messages),
                        'emails': email_details,
                        'timestamp': datetime.utcnow().isoformat()
                    },
                    processed=False
                )
                db.add(event)
                logger.info(f"[Gmail Poll] ✓ Created webhook event with {len(email_details)} email details for processing")
            else:
                logger.debug(f"[Gmail Poll] No new messages found for user {user.id}")
            
            # Update sync state
            if not sync_state:
                sync_state = SyncState(
                    user_id=user.id,
                    provider='gmail',
                    resource_type='emails'
                )
                db.add(sync_state)
            
            sync_state.last_sync_at = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            logger.error(f"Error polling Gmail for user {user.id}: {e}")
            db.rollback()
    
    def _poll_user_calendar(self, user: User, db: Session):
        """Poll Calendar for changes (if no webhook is active)"""
        try:
            # Check if there's an active webhook
            has_webhook = db.query(WebhookSubscription).filter(
                WebhookSubscription.user_id == user.id,
                WebhookSubscription.provider == 'calendar',
                WebhookSubscription.is_active == True
            ).first()
            
            if has_webhook:
                logger.debug(f"User {user.id} has active Calendar webhook, skipping poll")
                return
            
            # Get last sync state
            sync_state = db.query(SyncState).filter(
                SyncState.user_id == user.id,
                SyncState.provider == 'calendar',
                SyncState.resource_type == 'events'
            ).first()
            
            # Only poll if last sync was more than 1 minute ago
            if sync_state and sync_state.last_sync_at:
                # Make datetime timezone-aware to match database
                now_utc = datetime.utcnow().replace(tzinfo=sync_state.last_sync_at.tzinfo) if sync_state.last_sync_at.tzinfo else datetime.utcnow()
                time_since_sync = now_utc - sync_state.last_sync_at
                if time_since_sync.total_seconds() < 60:  # 1 minute
                    return
            
            logger.info(f"Polling Calendar for user {user.id}")
            
            # Use Calendar API to check for changes
            credentials = self.google_service.get_credentials(user, db)
            if not credentials:
                return
            
            from googleapiclient.discovery import build
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get events from last hour to next 24 hours
            now = datetime.utcnow()
            time_min = (now - timedelta(hours=1)).isoformat() + 'Z'
            time_max = (now + timedelta(hours=24)).isoformat() + 'Z'
            
            events = service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=10,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            event_list = events.get('items', [])
            
            if event_list:
                logger.info(f"[Calendar Poll] ✓ Found {len(event_list)} calendar events for user {user.id}")
                
                # Create a webhook event for processing
                event = WebhookEvent(
                    user_id=user.id,
                    provider='calendar',
                    event_type='calendar_update_poll',
                    resource_id=None,
                    payload={
                        'source': 'polling',
                        'event_count': len(event_list),
                        'timestamp': datetime.utcnow().isoformat()
                    },
                    processed=False
                )
                db.add(event)
            
            # Update sync state
            if not sync_state:
                sync_state = SyncState(
                    user_id=user.id,
                    provider='calendar',
                    resource_type='events'
                )
                db.add(sync_state)
            
            sync_state.last_sync_at = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            logger.error(f"Error polling Calendar for user {user.id}: {e}")
            db.rollback()


def main():
    """Main entry point for the worker"""
    logger.info("Starting Proactive Worker")
    worker = ProactiveWorker()
    
    try:
        worker.start()
    except KeyboardInterrupt:
        logger.info("Shutting down worker")
        worker.stop()


if __name__ == "__main__":
    main()

