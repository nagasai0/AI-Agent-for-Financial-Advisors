"""
Proactive agent logic for processing webhook events and taking autonomous actions
"""
from sqlalchemy.orm import Session
from models_temp import User, WebhookEvent, Instruction
from agent.runtime import AgentRuntime, SYSTEM_PROMPT
from services.google import GoogleService
from services.hubspot import HubSpotService
from typing import Dict, Optional
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class ProactiveAgent:
    """
    Evaluates webhook events and determines if autonomous actions should be taken
    based on ongoing instructions and event context
    """
    
    def __init__(self):
        self.agent_runtime = AgentRuntime()
        self.google_service = GoogleService()
        self.hubspot_service = HubSpotService()
        logger.info("ProactiveAgent initialized")
    
    async def process_webhook_event(self, event: WebhookEvent, db: Session) -> Dict:
        """
        Process a webhook event and determine if any proactive actions should be taken
        
        Returns dict with:
            - should_act: bool
            - actions_taken: list of actions
            - response: str (explanation of what was done)
        """
        logger.info(f"Processing webhook event {event.id} - Provider: {event.provider}, Type: {event.event_type}")
        
        try:
            # Get user
            user = db.query(User).filter(User.id == event.user_id).first()
            if not user:
                logger.error(f"User not found for event {event.id}")
                return {"should_act": False, "error": "User not found"}
            
            # Get event details based on provider
            event_context = await self._get_event_context(event, user, db)
            if not event_context:
                logger.warning(f"Could not retrieve context for event {event.id}")
                return {"should_act": False, "error": "No context available"}
            
            # Get active instructions
            instructions = self._get_active_instructions(user, db)
            
            # Build proactive prompt for the agent
            proactive_prompt = self._build_proactive_prompt(
                event=event,
                event_context=event_context,
                instructions=instructions
            )
            
            # Ask the agent if it should take action
            logger.info(f"Asking agent to evaluate event {event.id}")
            result = self.agent_runtime.process_message(
                user=user,
                message=proactive_prompt,
                db=db
            )
            
            logger.info(f"Agent evaluation complete for event {event.id}: {result.get('success')}")
            
            return {
                "should_act": result.get("success", False),
                "actions_taken": result.get("tool_calls", []),
                "response": result.get("response", ""),
                "event_id": event.id
            }
            
        except Exception as e:
            logger.error(f"Error processing webhook event {event.id}: {e}")
            return {"should_act": False, "error": str(e)}
    
    async def _get_event_context(self, event: WebhookEvent, user: User, db: Session) -> Optional[Dict]:
        """Get detailed context about the webhook event"""
        
        try:
            if event.provider == 'gmail':
                return await self._get_gmail_context(event, user, db)
            elif event.provider == 'calendar':
                return await self._get_calendar_context(event, user, db)
            elif event.provider == 'hubspot':
                return await self._get_hubspot_context(event, user, db)
            else:
                logger.warning(f"Unknown provider: {event.provider}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting event context: {e}")
            return None
    
    async def _get_gmail_context(self, event: WebhookEvent, user: User, db: Session) -> Optional[Dict]:
        """Get context for Gmail event - use payload emails or fetch new ones"""
        logger.info("Fetching Gmail context for event")
        
        try:
            # First check if email details are already in the payload
            payload = event.payload or {}
            if 'emails' in payload and payload['emails']:
                logger.info(f"Using {len(payload['emails'])} emails from webhook payload")
                return {
                    "new_emails": payload['emails'],
                    "count": len(payload['emails'])
                }
            
            # Otherwise, fetch from Gmail API
            from googleapiclient.discovery import build
            
            credentials = self.google_service.get_credentials(user, db)
            if not credentials:
                return None
            
            service = build('gmail', 'v1', credentials=credentials)
            
            # Get messages from last 5 minutes
            import time
            five_min_ago = int(time.time()) - 300
            
            results = service.users().messages().list(
                userId='me',
                q=f'after:{five_min_ago}',
                maxResults=5
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                logger.info("No new messages found")
                return {"new_emails": []}
            
            # Get details of each message
            email_details = []
            for msg in messages[:3]:  # Limit to 3 most recent
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
            
            return {
                "new_emails": email_details,
                "count": len(email_details)
            }
            
        except Exception as e:
            logger.error(f"Error fetching Gmail context: {e}")
            return None
    
    async def _get_calendar_context(self, event: WebhookEvent, user: User, db: Session) -> Optional[Dict]:
        """Get context for Calendar event - fetch recent changes"""
        logger.info("Fetching Calendar context for event")
        
        try:
            from googleapiclient.discovery import build
            from datetime import datetime, timedelta
            
            credentials = self.google_service.get_credentials(user, db)
            if not credentials:
                return None
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get events from last hour and next 24 hours
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
            
            event_list = []
            for evt in events.get('items', []):
                event_list.append({
                    'id': evt['id'],
                    'summary': evt.get('summary', 'No Title'),
                    'start': evt['start'].get('dateTime', evt['start'].get('date')),
                    'end': evt['end'].get('dateTime', evt['end'].get('date')),
                    'attendees': [att.get('email') for att in evt.get('attendees', [])],
                    'status': evt.get('status')
                })
            
            return {
                "recent_events": event_list,
                "count": len(event_list)
            }
            
        except Exception as e:
            logger.error(f"Error fetching Calendar context: {e}")
            return None
    
    async def _get_hubspot_context(self, event: WebhookEvent, user: User, db: Session) -> Optional[Dict]:
        """Get context for HubSpot event"""
        logger.info("Fetching HubSpot context for event")
        
        try:
            payload = event.payload or {}
            object_id = payload.get('object_id') or event.resource_id
            subscription_type = payload.get('subscription_type', '')
            
            if 'contact' in subscription_type:
                # Get contact details
                client = self.hubspot_service.get_client(user, db)
                if not client:
                    return None
                
                contact = client.crm.contacts.basic_api.get_by_id(
                    contact_id=object_id,
                    properties=['email', 'firstname', 'lastname', 'phone', 'company']
                )
                
                return {
                    "contact": {
                        'id': contact.id,
                        'email': contact.properties.get('email', ''),
                        'first_name': contact.properties.get('firstname', ''),
                        'last_name': contact.properties.get('lastname', ''),
                        'phone': contact.properties.get('phone', ''),
                        'company': contact.properties.get('company', '')
                    },
                    "event_type": payload.get('event_type', '')
                }
            
            return payload
            
        except Exception as e:
            logger.error(f"Error fetching HubSpot context: {e}")
            return None
    
    def _get_active_instructions(self, user: User, db: Session) -> str:
        """Get active ongoing instructions"""
        instructions = db.query(Instruction).filter(
            Instruction.user_id == user.id,
            Instruction.is_active == True
        ).all()
        
        if not instructions:
            return "No active ongoing instructions."
        
        instruction_text = "ACTIVE ONGOING INSTRUCTIONS:\n"
        for i, instruction in enumerate(instructions, 1):
            instruction_text += f"{i}. {instruction.content}\n"
        
        return instruction_text
    
    def _build_proactive_prompt(self, event: WebhookEvent, event_context: Dict, 
                               instructions: str) -> str:
        """Build the prompt for proactive agent evaluation"""
        
        prompt = f"""PROACTIVE EVENT EVALUATION - BE INTELLIGENT AND AUTONOMOUS

A new event has occurred that may require your attention:

PROVIDER: {event.provider}
EVENT TYPE: {event.event_type}
TIMESTAMP: {event.created_at.isoformat() if event.created_at else 'Unknown'}

EVENT DETAILS:
{json.dumps(event_context, indent=2)}

{instructions}

YOUR TASK: Intelligently evaluate this event and take appropriate action:

1. **Check Email Sender Against Instructions** (MOST IMPORTANT):
   - Look at the 'from' field of each new email
   - Check if the sender email address matches ANY ongoing instruction
   - Example: If instruction says "reply to emails from saithumati01@gmail.com", check if ANY email is from that exact address
   - If it matches, execute the action specified in the instruction immediately
   - Extract the email address from the 'from' field (e.g., "Name <email@example.com>" → "email@example.com")

2. **Check for Pending Tasks**: 
   - Use task_list(status="waiting") to see if this email/event is a REPLY to a pending task
   - If yes, RESUME that task immediately and complete next steps
   - Example: If you emailed Sara about meeting times and she replied, create the calendar event NOW

3. **Execute Ongoing Instructions**:
   - Check if any ongoing instructions apply to this event
   - Example: "Create HubSpot contact for unknown senders" → check if sender is in HubSpot
   - Take action automatically if instruction matches

4. **Answer Client Questions Proactively**:
   - If email asks "when is our meeting?", search calendar and reply
   - If email asks about account info, search HubSpot/emails and reply
   - Be helpful and responsive

5. **Handle Multi-Step Workflows**:
   - Don't just acknowledge - COMPLETE the full workflow
   - If reply has chosen time, create event + send confirmation + update HubSpot
   - If reply says times don't work, propose NEW times immediately

CRITICAL RULES:
- ALWAYS check the 'from' email address of new emails against ongoing instructions FIRST
- NEVER say "I see this email" without taking action if action is warranted
- ALWAYS check for waiting tasks when new emails arrive
- BE AUTONOMOUS - handle the full workflow, not just one step
- Use ALL available tools to complete tasks end-to-end
- When matching email addresses, be case-insensitive and extract the email from "Name <email>" format

If genuinely no action needed:
- Respond with "No action needed for this event."

Remember: You are EXTREMELY capable. Handle complex workflows completely and autonomously.
"""
        
        return prompt


# Singleton instance
proactive_agent = ProactiveAgent()

