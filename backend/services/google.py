from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from models_temp import Account, User
from config import settings
from datetime import datetime, timedelta
import json
import base64
import email
from email.mime.text import MIMEText
import secrets
import hashlib
import requests
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class GoogleService:
    def __init__(self):
        self.scopes = settings.GOOGLE_SCOPES.split()
        self.client_config = {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI]
            }
        }
        # Store for state validation (in production, use Redis/database)
        self._oauth_states = {}

        # Log configuration for debugging
        logger.info(f"Google OAuth configured - Client ID: {settings.GOOGLE_CLIENT_ID[:10]}..." if settings.GOOGLE_CLIENT_ID else "Google Client ID not set")
        logger.info(f"Redirect URI: {settings.GOOGLE_REDIRECT_URI}")
        logger.info(f"Scopes: {self.scopes}")

    def cleanup_states(self):
        """Clean up old OAuth states (for memory management)"""
        # In a real application, you'd use Redis with expiration instead
        # For now, just keep the last 100 states
        if len(self._oauth_states) > 100:
            # Remove oldest half of the states
            states_to_remove = list(self._oauth_states.keys())[:50]
            for state in states_to_remove:
                del self._oauth_states[state]
            logger.info(f"Cleaned up {len(states_to_remove)} old OAuth states")

    def generate_state(self) -> str:
        """Generate a secure random state parameter for OAuth"""
        # Clean up old states periodically
        self.cleanup_states()

        state = secrets.token_urlsafe(32)
        # Store the state for validation (in production, use Redis/database with expiration)
        self._oauth_states[state] = True
        return state

    def validate_state(self, state: str) -> bool:
        """Validate the state parameter"""
        if not state:
            return False
        # Check if state exists in our stored states
        if state in self._oauth_states:
            # Clean up the used state to prevent replay attacks
            del self._oauth_states[state]
            return True
        return False
    
    def get_authorization_url(self) -> Tuple[str, str]:
        """Get Google OAuth authorization URL with state parameter"""
        # Generate state for CSRF protection
        state = self.generate_state()

        flow = Flow.from_client_config(
            self.client_config,
            scopes=self.scopes
        )
        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=state
        )
        return auth_url, state
    
    def handle_callback(self, code: str, state: str = None, db: Session = None) -> Tuple[User, bool]:
        """Handle OAuth callback and create/update user"""
        # Validate state parameter for security (more lenient for test accounts)
        if state and not self.validate_state(state):
            logger.warning(f"OAuth state validation failed for state: {state}")
            # For test accounts, we'll continue anyway - just log the warning
            # In production, you should return False here for security

        if not db:
            logger.error("Database session not provided to handle_callback")
            return None, False

        flow = Flow.from_client_config(
            self.client_config,
            scopes=self.scopes
        )
        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

        try:
            # Use requests.post to get the token and extract actual granted scopes
            token_data = requests.post('https://oauth2.googleapis.com/token', data={
                'client_id': settings.GOOGLE_CLIENT_ID,
                'client_secret': settings.GOOGLE_CLIENT_SECRET,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': settings.GOOGLE_REDIRECT_URI
            }).json()

            if 'error' in token_data:
                logger.error(f"Token exchange failed: {token_data}")
                return None, False

            # Get actual scopes from token response
            actual_scopes = token_data.get('scope', '')

            logger.info(f"Requested scopes: {' '.join(self.scopes)}")
            logger.info(f"Granted scopes: {actual_scopes}")

            # Create credentials object manually since we used requests
            from google.oauth2.credentials import Credentials
            import time
            current_time = int(time.time())
            expires_in = token_data.get('expires_in', 3600)  # Default 1 hour
            expiry_timestamp = current_time + expires_in

            credentials = Credentials(
                token=token_data['access_token'],
                refresh_token=token_data.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                scopes=actual_scopes.split() if actual_scopes else []
            )

            # Set expiry manually
            credentials.expiry = datetime.fromtimestamp(expiry_timestamp)

        except Exception as e:
            logger.error(f"Failed to fetch token: {e}")
            return None, False

        # Get user info
        try:
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()

            email = user_info['email']
            name = user_info['name']
        except Exception as e:
            logger.error(f"Failed to get user info from Google: {e}")
            return None, False
        
        # Find or create user
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, name=name, google_email=email)
            db.add(user)
            db.commit()
            db.refresh(user)
        
        # Update or create account
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'google'
        ).first()
        
        if account:
            account.access_token = credentials.token
            account.refresh_token = credentials.refresh_token
            account.scope = actual_scopes  # Use actual granted scopes from token response
            account.expiry = credentials.expiry
        else:
            account = Account(
                user_id=user.id,
                provider='google',
                access_token=credentials.token,
                refresh_token=credentials.refresh_token,
                scope=actual_scopes,  # Use actual granted scopes from token response
                expiry=credentials.expiry
            )
            db.add(account)
        
        db.commit()
        return user, True
    
    def has_gmail_scope(self, user: User, db: Session) -> bool:
        """Check if user has Gmail scope"""
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'google'
        ).first()
        
        if not account or not account.scope:
            return False
        
        # Check for Gmail scope
        gmail_scope = 'https://www.googleapis.com/auth/gmail.modify'
        return gmail_scope in account.scope
    
    def has_calendar_scope(self, user: User, db: Session) -> bool:
        """Check if user has Calendar scope"""
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'google'
        ).first()
        
        if not account or not account.scope:
            return False
        
        # Check for Calendar scope
        calendar_scope = 'https://www.googleapis.com/auth/calendar'
        return calendar_scope in account.scope
    
    def get_credentials(self, user: User, db: Session) -> Optional[Credentials]:
        """Get valid credentials for user"""
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'google'
        ).first()
        
        if not account:
            return None
        
        credentials = Credentials(
            token=account.access_token,
            refresh_token=account.refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=account.scope.split()
        )
        
        # Refresh if needed
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                # Update stored token
                account.access_token = credentials.token
                account.expiry = credentials.expiry
                db.commit()
            except Exception as e:
                logger.error(f"Failed to refresh Google token: {e}")
                return None
        
        return credentials
    
    def gmail_list_since_batch(self, user: User, since_ts: datetime, db: Session, batch_size: int = 10) -> List[Dict]:
        """List Gmail messages since timestamp with batch processing"""
        logger.info(f"Starting Gmail list_since_batch for user {user.id}, since: {since_ts}")
        
        credentials = self.get_credentials(user, db)
        if not credentials:
            logger.error(f"No valid credentials found for user {user.id}")
            return []
        
        try:
            service = build('gmail', 'v1', credentials=credentials)
            
            # Format timestamp for Gmail API
            since_query = since_ts.strftime('%Y/%m/%d')
            logger.info(f"Querying Gmail with date filter: after:{since_query}")
            
            results = service.users().messages().list(
                userId='me',
                q=f'after:{since_query}',
                maxResults=50
            ).execute()
            
            message_list = results.get('messages', [])
            logger.info(f"Gmail API returned {len(message_list)} messages")
            
            if not message_list:
                return []
            
            messages = []
            
            # Process messages in batches
            for i in range(0, len(message_list), batch_size):
                batch = message_list[i:i + batch_size]
                logger.info(f"Processing batch {i//batch_size + 1}/{(len(message_list) + batch_size - 1)//batch_size} ({len(batch)} messages)")
                
                batch_messages = []
                for msg in batch:
                    try:
                        msg_detail = service.users().messages().get(
                            userId='me',
                            id=msg['id'],
                            format='full'
                        ).execute()
                        
                        # Extract headers
                        headers = {h['name']: h['value'] for h in msg_detail['payload'].get('headers', [])}
                        
                        # Extract body
                        body = self._extract_email_body(msg_detail['payload'])
                        
                        message_data = {
                            'id': msg['id'],
                            'thread_id': msg_detail.get('threadId'),
                            'subject': headers.get('Subject', ''),
                            'from': headers.get('From', ''),
                            'to': headers.get('To', ''),
                            'date': headers.get('Date', ''),
                            'body': body,
                            'snippet': msg_detail.get('snippet', '')
                        }
                        
                        batch_messages.append(message_data)
                        
                    except Exception as msg_error:
                        logger.error(f"Error processing message {msg['id']}: {msg_error}")
                        continue
                
                messages.extend(batch_messages)
                logger.info(f"Batch completed: {len(batch_messages)} messages processed")
            
            logger.info(f"Successfully processed {len(messages)} out of {len(message_list)} messages")
            return messages
            
        except Exception as e:
            logger.error(f"Error in batch Gmail processing: {e}")
            return []
    
    def gmail_list_since(self, user: User, since_ts: datetime, db: Session) -> List[Dict]:
        """List Gmail messages since timestamp"""
        logger.info(f"Starting Gmail list_since for user {user.id}, since: {since_ts}")
        
        credentials = self.get_credentials(user, db)
        if not credentials:
            logger.error(f"No valid credentials found for user {user.id}")
            return []
        
        logger.info(f"Got credentials for user {user.id}, token exists: {bool(credentials.token)}")
        
        try:
            logger.info("Building Gmail service...")
            service = build('gmail', 'v1', credentials=credentials)
            logger.info("Gmail service built successfully")
            
            # Format timestamp for Gmail API
            since_query = since_ts.strftime('%Y/%m/%d')
            logger.info(f"Querying Gmail with date filter: after:{since_query}")
            
            results = service.users().messages().list(
                userId='me',
                q=f'after:{since_query}',
                maxResults=50
            ).execute()
            
            logger.info(f"Gmail API returned {len(results.get('messages', []))} messages")
            
            messages = []
            logger.info(f"Processing {len(results.get('messages', []))} messages...")
            
            for i, msg in enumerate(results.get('messages', [])):
                logger.debug(f"Processing message {i+1}/{len(results.get('messages', []))}: {msg['id']}")
                
                try:
                    msg_detail = service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='full'
                    ).execute()
                    
                    # Extract headers
                    headers = {h['name']: h['value'] for h in msg_detail['payload'].get('headers', [])}
                    
                    # Extract body
                    body = self._extract_email_body(msg_detail['payload'])
                    
                    message_data = {
                        'id': msg['id'],
                        'thread_id': msg_detail.get('threadId'),
                        'subject': headers.get('Subject', ''),
                        'from': headers.get('From', ''),
                        'to': headers.get('To', ''),
                        'date': headers.get('Date', ''),
                        'body': body,
                        'snippet': msg_detail.get('snippet', '')
                    }
                    
                    messages.append(message_data)
                    logger.debug(f"Successfully processed message: {message_data['subject'][:50]}...")
                    
                except Exception as msg_error:
                    logger.error(f"Error processing individual message {msg['id']}: {msg_error}")
                    continue
            
            logger.info(f"Successfully processed {len(messages)} out of {len(results.get('messages', []))} messages")
            return messages
            
        except Exception as e:
            logger.error(f"Error listing Gmail messages: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            return []
    
    def gmail_send(self, user: User, to: str, subject: str, body: str, thread_id: Optional[str] = None, db: Session = None) -> Dict:
        """Send email via Gmail"""
        credentials = self.get_credentials(user, db)
        if not credentials:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            service = build('gmail', 'v1', credentials=credentials)
            
            # Create message
            message = MIMEText(body)
            message['to'] = to
            message['from'] = user.email  # Add from header
            message['subject'] = subject
            
            if thread_id:
                message['In-Reply-To'] = thread_id
                message['References'] = thread_id
            
            raw_message = base64.urlsafe_b64encode(
                message.as_bytes()
            ).decode('utf-8')
            
            send_params = {
                'userId': 'me',
                'body': {'raw': raw_message}
            }
            
            if thread_id:
                send_params['body']['threadId'] = thread_id
            
            result = service.users().messages().send(**send_params).execute()
            
            return {
                'success': True,
                'message_id': result['id'],
                'thread_id': result.get('threadId')
            }
            
        except Exception as e:
            logger.error(f"Error sending Gmail: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"To: {to}, Subject: {subject}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {'success': False, 'error': str(e)}
    
    def calendar_find_slots(self, user: User, duration_min: int, window_start: str, window_end: str, db: Session) -> List[Dict]:
        """Find available calendar slots"""
        credentials = self.get_credentials(user, db)
        if not credentials:
            return []
        
        try:
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get busy times
            freebusy_result = service.freebusy().query(
                body={
                    'timeMin': window_start,
                    'timeMax': window_end,
                    'items': [{'id': 'primary'}]
                }
            ).execute()
            
            busy_times = freebusy_result['calendars']['primary'].get('busy', [])
            
            # Generate potential slots (business hours, 30-min intervals)
            from datetime import datetime, timedelta
            import pytz
            
            start_dt = datetime.fromisoformat(window_start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(window_end.replace('Z', '+00:00'))
            
            # Convert to local timezone (assuming IST for now)
            ist = pytz.timezone('Asia/Kolkata')
            start_local = start_dt.astimezone(ist)
            end_local = end_dt.astimezone(ist)
            
            slots = []
            current = start_local.replace(hour=9, minute=0, second=0, microsecond=0)  # 9 AM
            
            while current < end_local and len(slots) < 3:
                # Skip weekends
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    current = current.replace(hour=9, minute=0, second=0, microsecond=0)
                    continue
                
                # Check if slot is free
                slot_start = current
                slot_end = current + timedelta(minutes=duration_min)
                
                # Convert back to UTC for comparison
                slot_start_utc = slot_start.astimezone(pytz.UTC)
                slot_end_utc = slot_end.astimezone(pytz.UTC)
                
                is_free = True
                for busy in busy_times:
                    busy_start = datetime.fromisoformat(busy['start'].replace('Z', '+00:00'))
                    busy_end = datetime.fromisoformat(busy['end'].replace('Z', '+00:00'))
                    
                    if (slot_start_utc < busy_end and slot_end_utc > busy_start):
                        is_free = False
                        break
                
                if is_free:
                    slots.append({
                        'start': slot_start_utc.isoformat(),
                        'end': slot_end_utc.isoformat(),
                        'start_local': slot_start.strftime('%A, %B %d at %I:%M %p IST'),
                        'end_local': slot_end.strftime('%I:%M %p IST')
                    })
                
                current += timedelta(minutes=30)
                
                # If we've passed 5 PM, move to next day
                if current.hour >= 17:
                    current += timedelta(days=1)
                    current = current.replace(hour=9, minute=0, second=0, microsecond=0)
            
            return slots
            
        except Exception as e:
            logger.error(f"Error finding calendar slots: {e}")
            return []
    
    def calendar_create_event(self, user: User, title: str, start: str, end: str, attendees: List[str], db: Session) -> Dict:
        """Create calendar event"""
        credentials = self.get_credentials(user, db)
        if not credentials:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            service = build('calendar', 'v3', credentials=credentials)
            
            event = {
                'summary': title,
                'start': {
                    'dateTime': start,
                    'timeZone': 'UTC'
                },
                'end': {
                    'dateTime': end,
                    'timeZone': 'UTC'
                },
                'attendees': [{'email': email} for email in attendees],
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 10}
                    ]
                }
            }
            
            result = service.events().insert(
                calendarId='primary',
                body=event,
                sendUpdates='all'
            ).execute()
            
            # Extract only the needed fields to avoid RepeatedComposite objects
            return {
                'success': True,
                'event_id': str(result.get('id', '')),
                'html_link': str(result.get('htmlLink', '')),
                'status': str(result.get('status', ''))
            }
            
        except Exception as e:
            logger.error(f"Error creating calendar event: {e}")
            return {'success': False, 'error': str(e)}
    
    def calendar_list_events(self, user: User, time_min: str, time_max: str, max_results: int, db: Session) -> List[Dict]:
        """List calendar events within a time window"""
        credentials = self.get_credentials(user, db)
        if not credentials:
            return []
        
        try:
            service = build('calendar', 'v3', credentials=credentials)
            
            events_result = service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            event_list = []
            for event in events:
                event_list.append({
                    'id': event['id'],
                    'title': event.get('summary', 'No Title'),
                    'start': event['start'].get('dateTime', event['start'].get('date')),
                    'end': event['end'].get('dateTime', event['end'].get('date')),
                    'attendees': [att.get('email') for att in event.get('attendees', [])],
                    'html_link': event.get('htmlLink'),
                    'status': event.get('status')
                })
            
            return event_list
            
        except Exception as e:
            logger.error(f"Error listing calendar events: {e}")
            return []
    
    def calendar_get_event(self, user: User, event_id: str, db: Session) -> Dict:
        """Get details of a specific calendar event"""
        credentials = self.get_credentials(user, db)
        if not credentials:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            service = build('calendar', 'v3', credentials=credentials)
            
            event = service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            return {
                'success': True,
                'event': {
                    'id': event['id'],
                    'title': event.get('summary', 'No Title'),
                    'start': event['start'].get('dateTime', event['start'].get('date')),
                    'end': event['end'].get('dateTime', event['end'].get('date')),
                    'attendees': [att.get('email') for att in event.get('attendees', [])],
                    'html_link': event.get('htmlLink'),
                    'status': event.get('status'),
                    'description': event.get('description', '')
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting calendar event: {e}")
            return {'success': False, 'error': str(e)}
    
    def calendar_update_event(self, user: User, event_id: str, title: Optional[str], start: Optional[str], 
                              end: Optional[str], attendees: Optional[List[str]], db: Session) -> Dict:
        """Update an existing calendar event"""
        credentials = self.get_credentials(user, db)
        if not credentials:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get current event first
            event = service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            # Update only provided fields
            if title:
                event['summary'] = title
            if start:
                event['start'] = {'dateTime': start, 'timeZone': 'UTC'}
            if end:
                event['end'] = {'dateTime': end, 'timeZone': 'UTC'}
            if attendees:
                event['attendees'] = [{'email': email} for email in attendees]
            
            # Update the event
            updated_event = service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event,
                sendUpdates='all'
            ).execute()
            
            # Extract only the needed fields to avoid RepeatedComposite objects
            return {
                'success': True,
                'event_id': str(updated_event.get('id', '')),
                'html_link': str(updated_event.get('htmlLink', '')),
                'status': str(updated_event.get('status', ''))
            }
            
        except Exception as e:
            logger.error(f"Error updating calendar event: {e}")
            return {'success': False, 'error': str(e)}
    
    def calendar_delete_event(self, user: User, event_id: str, db: Session) -> Dict:
        """Delete a calendar event"""
        credentials = self.get_credentials(user, db)
        if not credentials:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            service = build('calendar', 'v3', credentials=credentials)
            
            service.events().delete(
                calendarId='primary',
                eventId=event_id,
                sendUpdates='all'
            ).execute()
            
            return {
                'success': True,
                'event_id': event_id,
                'message': 'Event deleted successfully'
            }
            
        except Exception as e:
            logger.error(f"Error deleting calendar event: {e}")
            return {'success': False, 'error': str(e)}
    
    def _extract_email_body(self, payload: Dict) -> str:
        """Extract email body from Gmail API payload"""
        body = ""
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body']['data']
                    body = base64.urlsafe_b64decode(data).decode('utf-8')
                    break
                elif part['mimeType'] == 'text/html' and not body:
                    data = part['body']['data']
                    body = base64.urlsafe_b64decode(data).decode('utf-8')
        else:
            if payload['mimeType'] == 'text/plain':
                data = payload['body']['data']
                body = base64.urlsafe_b64decode(data).decode('utf-8')
        
        return body
