try:
    from hubspot import HubSpot
    from hubspot.crm.contacts import ApiException
    HUBSPOT_AVAILABLE = True
except ImportError as e:
    logger.error(f"HubSpot import failed: {e}")
    HUBSPOT_AVAILABLE = False
    # Create dummy classes to prevent errors
    class HubSpot:
        def __init__(self, *args, **kwargs):
            pass
    class ApiException(Exception):
        pass
from sqlalchemy.orm import Session
from models_temp import Account, User
from config import settings
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlencode
import logging
import requests
import ssl
import certifi
import urllib3

logger = logging.getLogger(__name__)

class HubSpotService:
    def __init__(self):
        self.client_id = settings.HUBSPOT_CLIENT_ID
        self.client_secret = settings.HUBSPOT_CLIENT_SECRET
        self.redirect_uri = settings.HUBSPOT_REDIRECT_URI
        
        # Configure SSL context for HubSpot API calls
        self._configure_ssl()
    
    def _configure_ssl(self):
        """Configure SSL settings for HubSpot API calls"""
        try:
            # Disable SSL warnings for development
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # Set up SSL context with proper certificate verification
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            
            # Use certifi for certificate bundle
            ssl_context.load_verify_locations(certifi.where())
            
            # Configure requests session with SSL context
            self.session = requests.Session()
            self.session.verify = certifi.where()
            
            logger.info(f"SSL configured successfully using certifi bundle: {certifi.where()}")
            
        except Exception as e:
            logger.warning(f"SSL configuration failed, using default settings: {e}")
            # Fallback to default session
            self.session = requests.Session()
    
    
    def get_authorization_url(self) -> str:
        """Get HubSpot OAuth authorization URL"""
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'scope': settings.HUBSPOT_SCOPES
        }
        auth_url = f"https://app.hubspot.com/oauth/authorize?{urlencode(params)}"
        logger.info(f"HubSpot auth URL: {auth_url}")
        return auth_url
    
    def handle_callback(self, code: str, db: Session, existing_user_id: str = None) -> Tuple[User, bool]:
        """Handle OAuth callback and create/update user
        
        Args:
            code: OAuth authorization code
            db: Database session
            existing_user_id: If provided, link HubSpot account to this existing user
        """
        logger.info("Starting HubSpot OAuth token exchange...")
        
        # Exchange code for tokens
        token_data = {
            'grant_type': 'authorization_code',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': self.redirect_uri,
            'code': code
        }
        
        try:
            response = requests.post('https://api.hubapi.com/oauth/v1/token', data=token_data)
            
            if response.status_code != 200:
                logger.error(f"HubSpot token exchange failed: {response.status_code} - {response.text}")
                return None, False
            
            tokens = response.json()
            access_token = tokens['access_token']
            refresh_token = tokens.get('refresh_token')
            
            logger.info("HubSpot token exchange successful")

            # Check if HubSpot returns scope information in token response
            actual_scopes = tokens.get('scope', '')

            if actual_scopes:
                logger.info(f"HubSpot - Requested scopes: {settings.HUBSPOT_SCOPES}")
                logger.info(f"HubSpot - Granted scopes from token: {actual_scopes}")
            else:
                # HubSpot doesn't return scope in token response, use requested scopes
                actual_scopes = settings.HUBSPOT_SCOPES
                logger.info(f"HubSpot - Requested scopes: {actual_scopes}")
                logger.info(f"HubSpot - Using requested scopes (no scope info in token response)")

            # Get user info - use the correct HubSpot API endpoint
            headers = {'Authorization': f'Bearer {access_token}'}
            user_response = requests.get('https://api.hubapi.com/oauth/v1/access-tokens/' + access_token, headers=headers)

            if user_response.status_code != 200:
                logger.error(f"HubSpot user info failed: {user_response.status_code} - {user_response.text}")
                return None, False

            user_info = user_response.json()
            email = user_info['user']
            logger.info(f"HubSpot user email: {email}")
            
            # If existing_user_id provided, use that user (linking HubSpot to existing account)
            if existing_user_id:
                user = db.query(User).filter(User.id == existing_user_id).first()
                if not user:
                    logger.error(f"Existing user {existing_user_id} not found")
                    return None, False
                logger.info(f"Linking HubSpot account to existing user: {user.email}")
            else:
                # Find or create user based on HubSpot email
                user = db.query(User).filter(User.email == email).first()
                if not user:
                    logger.info(f"Creating new user for HubSpot email: {email}")
                    user = User(email=email, name=email.split('@')[0])
                    db.add(user)
                    db.commit()
                    db.refresh(user)
                else:
                    logger.info(f"Found existing user for email: {email}")
        
        except Exception as e:
            logger.error(f"Error in HubSpot OAuth callback: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            return None, False
        
        # Update or create account
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'hubspot'
        ).first()
        
        if account:
            account.access_token = access_token
            account.refresh_token = refresh_token
            account.scope = actual_scopes  # Use actual granted scopes from token response
        else:
            account = Account(
                user_id=user.id,
                provider='hubspot',
                access_token=access_token,
                refresh_token=refresh_token,
                scope=actual_scopes  # Use actual granted scopes from token response
            )
            db.add(account)
        
        db.commit()
        return user, True
    
    def get_client(self, user: User, db: Session) -> Optional[HubSpot]:
        """Get HubSpot client for user"""
        logger.info(f"Getting HubSpot client for user {user.id}")
        
        if not HUBSPOT_AVAILABLE:
            logger.error("HubSpot library not available - check installation")
            return None
        
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'hubspot'
        ).first()
        
        if not account:
            logger.warning(f"No HubSpot account found for user {user.id}")
            return None
        
        logger.info(f"Found HubSpot account for user {user.id}, token exists: {bool(account.access_token)}")
        
        try:
            # Configure HubSpot client with SSL settings
            client = HubSpot(access_token=account.access_token)
            
            # Apply SSL configuration to the client's underlying session
            if hasattr(client, '_api_client') and hasattr(client._api_client, 'rest_client'):
                client._api_client.rest_client.pool_manager.configure_from_url(
                    'https://api.hubapi.com',
                    cert_reqs='CERT_REQUIRED',
                    ca_certs=certifi.where()
                )
            
            logger.info("HubSpot client created successfully with SSL configuration")
            return client
        except Exception as e:
            logger.error(f"Error creating HubSpot client: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            return None
    
    def is_connected(self, user: User, db: Session) -> bool:
        """Check if HubSpot is properly connected and working"""
        if not HUBSPOT_AVAILABLE:
            return False
            
        account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'hubspot'
        ).first()
        
        if not account:
            return False
        
        try:
            # Test the connection by making a simple API call
            client = self.get_client(user, db)
            if not client:
                return False
            
            # Try to get a single contact to test the connection
            result = client.crm.contacts.basic_api.get_page(limit=1)
            return True
        except Exception as e:
            logger.warning(f"HubSpot connection test failed for user {user.id}: {e}")
            return False
    
    def hs_search_contact(self, user: User, query: str, db: Session) -> List[Dict]:
        """Search HubSpot contacts"""
        client = self.get_client(user, db)
        if not client:
            return []
        
        try:
            # Search by email or name
            if '@' in query:
                # Search by email
                results = client.crm.contacts.basic_api.get_page(
                    limit=10,
                    properties=['email', 'firstname', 'lastname', 'hs_object_id', 'notes']
                )
                contacts = []
                for contact in results.results:
                    if query.lower() in contact.properties.get('email', '').lower():
                        contacts.append({
                            'id': contact.id,
                            'email': contact.properties.get('email', ''),
                            'first_name': contact.properties.get('firstname', ''),
                            'last_name': contact.properties.get('lastname', ''),
                            'name': f"{contact.properties.get('firstname', '')} {contact.properties.get('lastname', '')}".strip(),
                            'notes': contact.properties.get('notes', '')
                        })
                return contacts
            else:
                # Search by name
                results = client.crm.contacts.basic_api.get_page(
                    limit=10,
                    properties=['email', 'firstname', 'lastname', 'hs_object_id', 'notes']
                )
                contacts = []
                for contact in results.results:
                    name = f"{contact.properties.get('firstname', '')} {contact.properties.get('lastname', '')}".strip()
                    if query.lower() in name.lower():
                        contacts.append({
                            'id': contact.id,
                            'email': contact.properties.get('email', ''),
                            'first_name': contact.properties.get('firstname', ''),
                            'last_name': contact.properties.get('lastname', ''),
                            'name': name,
                            'notes': contact.properties.get('notes', '')
                        })
                return contacts
                
        except Exception as e:
            logger.error(f"Error searching HubSpot contacts: {e}")
            return []
    
    def hs_create_contact(self, user: User, email: str, first_name: Optional[str] = None, last_name: Optional[str] = None, db: Session = None) -> Dict:
        """Create HubSpot contact"""
        client = self.get_client(user, db)
        if not client:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            properties = {'email': email}
            if first_name:
                properties['firstname'] = first_name
            if last_name:
                properties['lastname'] = last_name
            
            contact = client.crm.contacts.basic_api.create(
                properties=properties
            )
            
            return {
                'success': True,
                'contact_id': contact.id,
                'email': contact.properties.get('email', ''),
                'name': f"{contact.properties.get('firstname', '')} {contact.properties.get('lastname', '')}".strip()
            }
            
        except Exception as e:
            logger.error(f"Error creating HubSpot contact: {e}")
            return {'success': False, 'error': str(e)}
    
    def hs_create_note(self, user: User, contact_id: str, content: str, db: Session) -> Dict:
        """Create note as contact property (workaround - no note scopes available)"""
        client = self.get_client(user, db)
        if not client:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            from datetime import datetime
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            
            # Get existing notes from contact
            contact = client.crm.contacts.basic_api.get_by_id(
                contact_id=contact_id,
                properties=['notes']
            )
            
            existing_notes = contact.properties.get('notes', '')
            
            # Append new note with timestamp
            new_note = f"[{timestamp}] {content}"
            updated_notes = f"{existing_notes}\n\n{new_note}" if existing_notes else new_note
            
            # Update contact with new note
            client.crm.contacts.basic_api.update(
                contact_id=contact_id,
                properties={'notes': updated_notes}
            )
            
            return {
                'success': True,
                'note_id': f"{contact_id}_note_{int(datetime.utcnow().timestamp())}"
            }
            
        except Exception as e:
            logger.error(f"Error creating HubSpot note: {e}")
            return {'success': False, 'error': str(e)}
    
    def hs_get_contact_details(self, user: User, contact_id: str, db: Session) -> Dict:
        """Get detailed information about a specific HubSpot contact"""
        client = self.get_client(user, db)
        if not client:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            contact = client.crm.contacts.basic_api.get_by_id(
                contact_id=contact_id,
                properties=['email', 'firstname', 'lastname', 'phone', 'company', 'notes', 
                           'createdate', 'lastmodifieddate', 'hs_lead_status', 'lifecyclestage']
            )
            
            return {
                'success': True,
                'contact': {
                    'id': contact.id,
                    'email': contact.properties.get('email', ''),
                    'first_name': contact.properties.get('firstname', ''),
                    'last_name': contact.properties.get('lastname', ''),
                    'name': f"{contact.properties.get('firstname', '')} {contact.properties.get('lastname', '')}".strip(),
                    'phone': contact.properties.get('phone', ''),
                    'company': contact.properties.get('company', ''),
                    'notes': contact.properties.get('notes', ''),
                    'created_at': contact.properties.get('createdate', ''),
                    'updated_at': contact.properties.get('lastmodifieddate', ''),
                    'lead_status': contact.properties.get('hs_lead_status', ''),
                    'lifecycle_stage': contact.properties.get('lifecyclestage', '')
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting HubSpot contact details: {e}")
            return {'success': False, 'error': str(e)}
    
    def hs_update_contact(self, user: User, contact_id: str, email: Optional[str] = None, 
                         first_name: Optional[str] = None, last_name: Optional[str] = None,
                         phone: Optional[str] = None, company: Optional[str] = None, db: Session = None) -> Dict:
        """Update an existing HubSpot contact's information"""
        client = self.get_client(user, db)
        if not client:
            return {'success': False, 'error': 'No valid credentials'}
        
        try:
            # Build properties dict with only provided values
            properties = {}
            if email:
                properties['email'] = email
            if first_name:
                properties['firstname'] = first_name
            if last_name:
                properties['lastname'] = last_name
            if phone:
                properties['phone'] = phone
            if company:
                properties['company'] = company
            
            if not properties:
                return {'success': False, 'error': 'No properties provided to update'}
            
            # Update the contact
            updated_contact = client.crm.contacts.basic_api.update(
                contact_id=contact_id,
                properties=properties
            )
            
            return {
                'success': True,
                'contact_id': updated_contact.id,
                'email': updated_contact.properties.get('email', ''),
                'name': f"{updated_contact.properties.get('firstname', '')} {updated_contact.properties.get('lastname', '')}".strip()
            }
            
        except Exception as e:
            logger.error(f"Error updating HubSpot contact: {e}")
            return {'success': False, 'error': str(e)}
    
    def hs_get_recent_contacts(self, user: User, limit: int = 10, db: Session = None) -> List[Dict]:
        """Get recent HubSpot contacts"""
        logger.info(f"Getting recent HubSpot contacts for user {user.id}, limit: {limit}")
        
        if not HUBSPOT_AVAILABLE:
            logger.error("HubSpot library not available - cannot get contacts")
            return []
        
        client = self.get_client(user, db)
        if not client:
            logger.warning(f"No HubSpot client available for user {user.id}")
            return []
        
        try:
            logger.info("Calling HubSpot contacts API...")
            results = client.crm.contacts.basic_api.get_page(
                limit=limit,
                properties=['email', 'firstname', 'lastname', 'hs_object_id', 'createdate', 'notes']
            )
            
            logger.info(f"HubSpot API returned {len(results.results)} contacts")
            
            contacts = []
            for i, contact in enumerate(results.results):
                logger.debug(f"Processing contact {i+1}/{len(results.results)}: {contact.id}")
                
                contact_data = {
                    'id': contact.id,
                    'email': contact.properties.get('email', ''),
                    'first_name': contact.properties.get('firstname', ''),
                    'last_name': contact.properties.get('lastname', ''),
                    'name': f"{contact.properties.get('firstname', '')} {contact.properties.get('lastname', '')}".strip(),
                    'created_at': contact.properties.get('createdate', ''),
                    'notes': contact.properties.get('notes', '')
                }
                
                contacts.append(contact_data)
                logger.debug(f"Processed contact: {contact_data['name']} ({contact_data['email']})")
            
            logger.info(f"Successfully processed {len(contacts)} contacts")
            return contacts
            
        except Exception as e:
            logger.error(f"Error getting recent HubSpot contacts: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            return []
    
    def hs_get_recent_notes(self, user: User, limit: int = 10, db: Session = None) -> List[Dict]:
        """Get recent notes from contact notes property (workaround)"""
        logger.info(f"Getting recent HubSpot notes for user {user.id}, limit: {limit}")
        
        if not HUBSPOT_AVAILABLE:
            logger.error("HubSpot library not available - cannot get notes")
            return []
        
        client = self.get_client(user, db)
        if not client:
            logger.warning(f"No HubSpot client available for user {user.id}")
            return []
        
        try:
            logger.info("Calling HubSpot contacts API to get notes...")
            # Get recent contacts with notes
            results = client.crm.contacts.basic_api.get_page(
                limit=limit,
                properties=['email', 'firstname', 'lastname', 'notes', 'createdate']
            )
            
            logger.info(f"HubSpot API returned {len(results.results)} contacts for notes extraction")
            
            notes = []
            for i, contact in enumerate(results.results):
                logger.debug(f"Processing contact {i+1}/{len(results.results)} for notes: {contact.id}")
                
                contact_notes = contact.properties.get('notes', '')
                if contact_notes:
                    logger.debug(f"Found notes for contact {contact.id}: {len(contact_notes)} characters")
                    # Parse notes (split by double newline)
                    note_entries = contact_notes.split('\n\n')
                    logger.debug(f"Split into {len(note_entries)} note entries")
                    
                    for j, entry in enumerate(note_entries[-3:]):  # Last 3 notes per contact
                        note_data = {
                            'id': f"{contact.id}_note_{j}",
                            'body': entry,
                            'contact_id': contact.id,
                            'contact_name': f"{contact.properties.get('firstname', '')} {contact.properties.get('lastname', '')}".strip(),
                            'timestamp': contact.properties.get('createdate', '')
                        }
                        notes.append(note_data)
                        logger.debug(f"Added note: {entry[:50]}...")
                else:
                    logger.debug(f"No notes found for contact {contact.id}")
            
            logger.info(f"Successfully extracted {len(notes)} notes from {len(results.results)} contacts")
            return notes[:limit]
            
        except Exception as e:
            logger.error(f"Error getting recent HubSpot notes: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            return []