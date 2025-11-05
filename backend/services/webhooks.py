"""
Webhook handlers for Gmail, Google Calendar, and HubSpot
Handles incoming webhook notifications and queues events for processing
"""
from sqlalchemy.orm import Session
from models_temp import User, WebhookEvent, WebhookSubscription
from typing import Dict, Optional
import logging
from datetime import datetime
import json
import uuid

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handle webhook events from Gmail, Calendar, and HubSpot"""
    
    def __init__(self):
        logger.info("WebhookHandler initialized")
    
    def handle_gmail_notification(self, channel_id: str, resource_id: str, 
                                  message_number: str, db: Session) -> bool:
        """
        Handle Gmail push notification
        
        Gmail sends notifications when mailbox changes occur.
        We need to fetch the actual changes using the Gmail API.
        """
        logger.info(f"Gmail webhook received - Channel: {channel_id}, Resource: {resource_id}, Message: {message_number}")
        
        try:
            # Find the subscription to get the user
            subscription = db.query(WebhookSubscription).filter(
                WebhookSubscription.channel_id == channel_id,
                WebhookSubscription.provider == 'gmail',
                WebhookSubscription.is_active == True
            ).first()
            
            if not subscription:
                logger.warning(f"No active subscription found for channel {channel_id}")
                return False
            
            # Create webhook event for processing
            event = WebhookEvent(
                user_id=subscription.user_id,
                provider='gmail',
                event_type='mailbox_update',
                resource_id=resource_id,
                payload={
                    'channel_id': channel_id,
                    'message_number': message_number,
                    'timestamp': datetime.utcnow().isoformat()
                },
                processed=False
            )
            db.add(event)
            db.commit()
            
            logger.info(f"Gmail webhook event created: {event.id} for user {subscription.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling Gmail webhook: {e}")
            db.rollback()
            return False
    
    def handle_calendar_notification(self, channel_id: str, resource_id: str,
                                     resource_state: str, db: Session) -> bool:
        """
        Handle Google Calendar push notification
        
        Calendar sends notifications when events change.
        resource_state can be: 'sync', 'exists', 'not_exists'
        """
        logger.info(f"Calendar webhook received - Channel: {channel_id}, State: {resource_state}")
        
        try:
            # Find the subscription to get the user
            subscription = db.query(WebhookSubscription).filter(
                WebhookSubscription.channel_id == channel_id,
                WebhookSubscription.provider == 'calendar',
                WebhookSubscription.is_active == True
            ).first()
            
            if not subscription:
                logger.warning(f"No active subscription found for channel {channel_id}")
                return False
            
            # Skip 'sync' events (initial sync confirmation)
            if resource_state == 'sync':
                logger.info("Skipping calendar sync event")
                return True
            
            # Create webhook event for processing
            event = WebhookEvent(
                user_id=subscription.user_id,
                provider='calendar',
                event_type=f'calendar_{resource_state}',
                resource_id=resource_id,
                payload={
                    'channel_id': channel_id,
                    'resource_state': resource_state,
                    'timestamp': datetime.utcnow().isoformat()
                },
                processed=False
            )
            db.add(event)
            db.commit()
            
            logger.info(f"Calendar webhook event created: {event.id} for user {subscription.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling Calendar webhook: {e}")
            db.rollback()
            return False
    
    def handle_hubspot_webhook(self, subscription_type: str, object_id: str,
                               event_type: str, payload: Dict, db: Session) -> bool:
        """
        Handle HubSpot webhook notification
        
        HubSpot sends webhooks for various object changes:
        - contact.creation, contact.propertyChange, contact.deletion
        - deal.creation, deal.propertyChange, deal.deletion
        """
        logger.info(f"HubSpot webhook received - Type: {subscription_type}, Event: {event_type}, Object: {object_id}")
        
        try:
            # Extract portal ID from payload to find user
            portal_id = payload.get('portalId')
            
            # Find subscription (we'll need to store portal_id in subscription)
            # For now, we'll create the event and match user during processing
            event = WebhookEvent(
                user_id=None,  # Will be set during processing
                provider='hubspot',
                event_type=f'{subscription_type}_{event_type}',
                resource_id=object_id,
                payload={
                    'subscription_type': subscription_type,
                    'object_id': object_id,
                    'event_type': event_type,
                    'portal_id': portal_id,
                    'data': payload,
                    'timestamp': datetime.utcnow().isoformat()
                },
                processed=False
            )
            db.add(event)
            db.commit()
            
            logger.info(f"HubSpot webhook event created: {event.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling HubSpot webhook: {e}")
            db.rollback()
            return False
    
    def get_unprocessed_events(self, db: Session, limit: int = 100) -> list:
        """Get unprocessed webhook events"""
        return db.query(WebhookEvent).filter(
            WebhookEvent.processed == False
        ).order_by(WebhookEvent.created_at).limit(limit).all()
    
    def mark_event_processed(self, event_id: str, db: Session, error: Optional[str] = None):
        """Mark a webhook event as processed"""
        event = db.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()
        if event:
            event.processed = True
            event.processed_at = datetime.utcnow()
            if error:
                event.error = error
            db.commit()

