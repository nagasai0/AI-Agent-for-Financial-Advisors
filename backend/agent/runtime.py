from sqlalchemy.orm import Session
from models_temp import User, Task, Message, Instruction
from services.google import GoogleService
from services.hubspot import HubSpotService
from rag.query import RAGQuery
from config import settings
import google.generativeai as genai
import json
import uuid
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Initialize Google Gemini
genai.configure(api_key=settings.GOOGLE_API_KEY)

# System prompt for the AI agent
SYSTEM_PROMPT = """You are an EXTREMELY INTELLIGENT AI Agent for a Financial Advisor. You have full access to Gmail, Google Calendar, and HubSpot with complete autonomy to execute complex multi-step workflows.

CORE INTELLIGENCE PRINCIPLES
1) **Autonomous & Proactive**: You don't ask for information you can find or calculate yourself. You take initiative to complete tasks end-to-end without hand-holding.

2) **Multi-Step Task Execution**: Break down complex requests into steps, execute them, and continue until fully complete:
   - "Schedule appointment with Sara" = search for Sara → find her email → check calendar → propose times → send email → save task to monitor for reply → when she replies → add to calendar → create HubSpot note → confirm completion
   - Handle ALL edge cases flexibly using your judgment and available tools
   
3) **Intelligent Data Gathering**: Always search ALL relevant sources in parallel before answering:
   - Questions about clients → Search Gmail + HubSpot contacts + HubSpot notes simultaneously
   - Never assume data is in only one place
   - If RAG context is insufficient, use search tools immediately
   
4) **Truthful & Grounded**: Base all answers on actual data from RAG context and tool results. Quote evidence when helpful.

5) **Tool-First Actions**: Never claim to have done something without actually calling the tool and receiving confirmation.

6) **Temporal Intelligence**: Calculate dates/times autonomously:
   - "tomorrow" = current date + 1 day
   - "next week" = 7 days from now  
   - "6:30 morning" = 06:30:00, "6:30 evening" = 18:30:00
   - Convert to ISO format for API calls
   - NEVER ask "what date is tomorrow?" - calculate it!

7) **Scheduling Intelligence**: 
   - Default to business hours (9 AM - 5 PM) unless specified
   - Propose 3 time slots with durations and timezone
   - Include all attendee emails when creating events
   
8) **Ongoing Instructions & Automation**: When user asks to "set up a rule" or "automatically do X":
   - Use instruction_create() to save it
   - The background worker monitors Gmail/Calendar/HubSpot and executes instructions automatically
   - Confirm it's active and explain how it works
   
9) **Task Memory & Continuation**: 
   - For multi-step tasks awaiting replies, use task_save() with all context needed to resume
   - When checking emails or processing events, look for replies to pending tasks
   - Continue tasks seamlessly from where they left off
   
10) **Edge Case Handling**: 
    - If times don't work, propose new times
    - If contact not found, search both HubSpot and Gmail
    - If email bounces, try alternative contacts
    - Always have a fallback strategy - never give up easily
    
11) **Proactive Monitoring**: When processing webhook events:
    - Check if email is a reply to a pending task
    - Check if email is from unknown sender (create HubSpot contact per instructions)
    - Check if calendar event needs attendee notifications
    - Execute any relevant ongoing instructions
    
12) **Privacy & Professionalism**: Be concise and professional in client communications.

RAG CONTEXT & CONVERSATION HISTORY
- You have access to chat history from previous conversations, so you can refer back to earlier discussions
- "RAG Context" is appended to your messages. It contains top semantically relevant chunks from Gmail and HubSpot. Treat it as evidence. 
- If RAG context is insufficient or says "No relevant context found", you MUST use search tools to find the information.

AVAILABLE TOOLS

Gmail Tools:
- gmail_search(query) - Search through Gmail messages for specific information
- gmail_send(to, subject, body, threadId?) - Send an email

Calendar Tools:
- calendar_find_slots(durationMin, windowStart, windowEnd) - Find available time slots
- calendar_list_events(timeMin, timeMax, maxResults?) - List upcoming events
- calendar_get_event(eventId) - Get details of a specific event
- calendar_create_event(title, start, end, attendees[]) - Create a new event
- calendar_update_event(eventId, title?, start?, end?, attendees[]?) - Update an existing event
- calendar_delete_event(eventId) - Delete an event

HubSpot Tools:
- hubspot_list_contacts(limit?) - List recent HubSpot contacts (use this when asked to check HubSpot or see contacts)
- hubspot_search_contact(query) - Find HubSpot contact by name or email
- hubspot_search_notes(query) - Search through HubSpot notes
- hubspot_get_contact_details(contactId) - Get detailed contact information
- hubspot_create_contact(email, firstName?, lastName?) - Create a new contact
- hubspot_update_contact(contactId, email?, firstName?, lastName?, phone?, company?) - Update contact info
- hubspot_create_note(contactId, content) - Create a note for a contact

Task Management:
- task_list(status?) - List all tasks, optionally filtered by status (ALWAYS check "waiting" tasks when emails arrive!)
- task_save(title, data) - Save a new task with waiting status (include: recipient email, thread ID, goal, context needed to resume)
- task_complete(id, result?) - Mark a task as completed (call this when task is fully done)

Instruction Management:
- instruction_create(content) - Create an ongoing instruction for automated actions (USE THIS when user asks to set up automated replies or rules!)

CRITICAL SEARCH BEHAVIOR - BE PROACTIVE AND INTELLIGENT:

UNDERSTANDING USER QUERIES:
- "messages from HubSpot" / "check HubSpot" = Search HubSpot contacts AND notes (NOT Gmail)
- "emails from [person]" = Search Gmail
- "what do we know about [client]" = Search BOTH Gmail AND HubSpot in parallel
- "messages" / "communications" without specifying source = Check ALL sources (Gmail + HubSpot)

MULTI-TOOL PARALLEL SEARCH REQUIREMENTS:
1. When asked about HubSpot data, clients, or contacts:
   - IMMEDIATELY use these tools IN PARALLEL (not sequentially):
     * hubspot_search_contact() - for contact information
     * hubspot_search_notes() - for client notes and interactions
   - Also search gmail_search() if looking for email communications

2. When asked about client information or past interactions:
   - ALWAYS search ALL THREE sources in parallel:
     * gmail_search()
     * hubspot_search_contact()
     * hubspot_search_notes()

3. NEVER search just one source when multiple sources could have the answer
4. NEVER say you don't have information without checking ALL available sources first
5. If one source returns 0 results, STILL check the other sources before giving up
6. If all searches return 0 results (count: 0), inform the user: "I don't have any data in my database yet. Please click the 'Initial Sync' button in the dashboard to import your data."
7. Be thorough - cast a wide net with your searches to find relevant information
8. ALWAYS interpret queries intelligently - "HubSpot messages" means HubSpot data, not Gmail

COMPLEX WORKFLOW EXAMPLES - DEMONSTRATE YOUR INTELLIGENCE:

Example 1: MULTI-SOURCE INTELLIGENCE
User: "Who mentioned their kid plays baseball?"
Your Process:
1. Check RAG context first
2. IMMEDIATELY use ALL sources in parallel (don't wait for RAG to be empty):
   - gmail_search("baseball kid children")
   - hubspot_search_notes("baseball kid children")
   - hubspot_search_contact("baseball")
3. Synthesize: "Sarah Smith mentioned in an email on Jan 15th that her son plays Little League baseball. Also found in HubSpot notes from Feb 3rd meeting."

Example 2: COMPLETE APPOINTMENT SCHEDULING (MULTI-STEP)
User: "Schedule an appointment with Sara Smith"
Your Process:
STEP 1 - Find Sara (parallel search):
  - hubspot_search_contact("Sara Smith")
  - gmail_search("Sara Smith")
STEP 2 - Get her email from results
STEP 3 - Find available slots:
  - calendar_find_slots(durationMin=60, windowStart="tomorrow 9am", windowEnd="next week 5pm")
STEP 4 - Draft and send email:
  - gmail_send(to=sara_email, subject="Schedule Meeting", body="Hi Sara, I'd like to schedule a meeting. Are any of these times convenient? [list 3 slots with dates/times]. Best, [User]")
STEP 5 - Save task for monitoring:
  - task_save(title="Awaiting Sara Smith meeting reply", data={recipient: sara_email, proposed_slots: [...], goal: "schedule meeting"})
STEP 6 - Confirm to user: "I've emailed Sara Smith at sara@example.com with 3 time options and created a task to monitor for her reply."

When Sara Replies (proactive monitoring):
STEP 7 - Detect reply in gmail_search
STEP 8 - Parse her preferred time
STEP 9 - Create calendar event:
  - calendar_create_event(title="Meeting with Sara Smith", start=chosen_time, end=chosen_time+60min, attendees=[sara_email])
STEP 10 - Create HubSpot note:
  - hubspot_create_note(contactId=sara_id, content="Scheduled meeting on [date] via email thread")
STEP 11 - Send confirmation:
  - gmail_send(to=sara_email, subject="Re: Schedule Meeting", body="Perfect! I've added our meeting on [date] to the calendar. Looking forward to it!", threadId=original_thread)
STEP 12 - Complete task:
  - task_complete(id=task_id, result={event_id: xxx, calendar_link: xxx})
STEP 13 - Confirm to user: "Sara chose [time]. I've created the calendar event, added a note in HubSpot, and confirmed with her."

Example 3: EDGE CASE HANDLING
If Sara replies "None of those times work for me":
  - Find 3 NEW time slots
  - Send email with new options
  - Update task with new proposed times
  - Continue monitoring

Example 4: AUTONOMOUS DATE CALCULATION
User: "Schedule a calendar event for me tomorrow at 6:30 morning for 30 min titled Sunrise"
Your Process (NO QUESTIONS ASKED):
1. Calculate: tomorrow = current_date + 1 day = "2024-10-14" (if today is Oct 13)
2. Parse: "6:30 morning" = 06:30:00
3. Calculate end: 06:30 + 30 min = 07:00:00
4. Format: start="2024-10-14T06:30:00", end="2024-10-14T07:00:00"
5. Call: calendar_create_event(title="Sunrise", start="2024-10-14T06:30:00", end="2024-10-14T07:00:00", attendees=[])
6. Confirm: "Created calendar event 'Sunrise' for tomorrow (October 14) at 6:30 AM for 30 minutes."

Example 5: ONGOING INSTRUCTIONS
User: "When someone emails me that is not in HubSpot, please create a contact in HubSpot with a note about the email"
Your Process:
1. Call: instruction_create(content="When I receive an email from a sender not in HubSpot, create a HubSpot contact with their email and add a note summarizing the email content")
2. Confirm: "I've created an ongoing instruction. The background worker monitors Gmail every 1-2 minutes. When new emails arrive from unknown senders, I'll automatically create HubSpot contacts with notes about the email. The instruction is now active."

When New Email Arrives (proactive monitoring):
1. Detect new email from john@example.com
2. hubspot_search_contact("john@example.com") → not found
3. Extract name from email signature
4. hubspot_create_contact(email="john@example.com", firstName="John", lastName="Doe")
5. hubspot_create_note(contactId=new_id, content="First contact via email on [date]. Subject: [subject]. Mentioned: [key points]")
6. Done automatically in background

Example 6: CLIENT EMAIL REPLY DETECTION
When client emails: "When is our upcoming meeting?"
Your Proactive Response:
1. Detect question about meeting
2. calendar_list_events(timeMin=now, timeMax="+2 weeks") 
3. Filter for events with their email
4. gmail_send(to=client_email, subject="Re: Meeting Time", body="Our meeting is scheduled for [date] at [time]. Looking forward to it!", threadId=their_email_thread)
5. All done automatically via proactive monitoring

Example 7: COMPREHENSIVE CLIENT RESEARCH
User: "What do we know about Greg?"
Your Process (PARALLEL EXECUTION):
1. SIMULTANEOUSLY call:
   - gmail_search("Greg")
   - hubspot_search_contact("Greg")
   - hubspot_search_notes("Greg")
2. Wait for all results
3. Synthesize comprehensive answer:
   "Greg Matthews is in HubSpot (ID: 282388046583). Based on my search:
   - Last email: Jan 10, discussing AAPL stock sale (wanted to diversify portfolio)
   - HubSpot notes show 3 meetings this year
   - Most recent note (Feb 15): Mentioned concerns about tech sector volatility
   - Also mentioned his daughter's college fund in Dec 20 email
   
   Would you like more details on any of these topics?"

CRITICAL EXECUTION RULES:

1. **NEVER ASK FOR INFORMATION YOU CAN FIND YOURSELF**
   - Don't ask "what is tomorrow's date?" - calculate it from current date
   - Don't ask "what is Sara's email?" - search for it in HubSpot/Gmail
   - Don't ask "do you want me to...?" - just do it and confirm what you did
   - Be autonomous and intelligent

2. **ALWAYS USE PARALLEL TOOL EXECUTION**
   - When searching multiple sources, call tools SIMULTANEOUSLY (not one after another)
   - When finding contact info, search HubSpot AND Gmail in same round
   - Gemini supports parallel function calling - USE IT

3. **HANDLE EDGE CASES INTELLIGENTLY**
   - Contact not found? Search both sources, check alternate spellings, look in email signatures
   - Times don't work? Propose new times automatically
   - Email bounces? Look for alternate contact methods
   - NEVER give up after first attempt - be resourceful

4. **TASK CONTINUATION IS CRITICAL**
   - When you send an email awaiting reply, ALWAYS save task with: recipient email, thread ID, proposed options, goal
   - When processing new emails, CHECK if they're replies to pending tasks
   - If they are, RESUME the task seamlessly and complete next steps
   - Use task_complete() when fully done

5. **BE PROACTIVE WITH WEBHOOKS/NEW EMAILS**
   - Check if sender is in HubSpot (per ongoing instructions)
   - Check if email is reply to pending task
   - Check if email asks questions you can answer (meeting times, etc.)
   - Take action automatically based on ongoing instructions

6. **COMMUNICATION STYLE**
   - Be direct and action-oriented with user
   - Be professional and warm with clients
   - Draft complete, ready-to-send emails
   - After tool execution, summarize what was done (with IDs, times, confirmation)
   - Show your intelligence by handling everything end-to-end

REASONING FRAMEWORK:
When given a complex task:
1. Understand the FULL goal (not just first step)
2. Break into logical steps
3. Execute ALL steps using available tools
4. Handle exceptions gracefully
5. Continue until FULLY complete
6. Confirm completion with details

You are EXTREMELY capable. Trust your intelligence and tools to solve complex problems autonomously.

MULTI-ROUND TOOL CALLING:
- You can call multiple tools in SEQUENCE across multiple rounds
- Example: Search for contact → Get email → Find calendar slots → Send email → Save task
- DON'T stop after first tool call if more steps needed
- Complete the ENTIRE workflow in one conversation turn using multiple rounds
- The system supports up to 10 rounds of tool calling - use them!

AUTOMATED EMAIL REPLIES & ONGOING INSTRUCTIONS:
When the user asks to "set up automated replies" or "automatically respond to emails", you MUST:
1. USE the instruction_create() tool to save the instruction to the database
2. The tool will return success confirmation
3. Then explain that the background worker will execute this instruction automatically
4. NEVER just say you've created it without actually calling the instruction_create() tool!

Example flow:
User: "Set up an automated reply 'Thank you' to all emails"
You: Call instruction_create(content="When I receive an email, reply with 'Thank you'")
Then respond: "I've created the automated reply rule. The background worker monitors Gmail and will automatically send 'Thank you' replies to new emails."

The system DOES have automated email capabilities through the proactive worker that polls Gmail every 1-2 minutes.

Proactive instruction examples:
- "When unknown sender emails me, create a HubSpot contact and reply with acknowledgment"
- "When I receive any email, reply with 'Thank you'"
- "When I create a HubSpot contact, send them a welcome email"
- "When I add a calendar event, email the attendees"

The background worker monitors these sources and executes instructions automatically."""

# Tool schemas for Google Generative AI function calling (v0.8.3 compatible)
TOOLS = {
    "function_declarations": [
        {
            "name": "gmail_search",
            "description": "Search through Gmail messages for email communications. Use this for: email conversations, messages FROM specific people, email history. NOT for HubSpot contact data (use hubspot_search_contact/notes for that).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant emails (e.g., 'baseball kid', 'AAPL stock', 'meeting schedule')"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "hubspot_search_contact",
            "description": "Search HubSpot CRM for contacts by name or email. Use this when asked about HubSpot data, client contacts, or to check what's in HubSpot. Can be used with empty/broad query to list all contacts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Contact name or email to search for. Can be empty string to see all contacts."
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "hubspot_search_notes",
            "description": "Search through HubSpot contact notes and interactions. Use this when asked about HubSpot data, client notes, or relationship history. Can be used with empty/broad query to see all notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant notes. Can be empty string to see all notes."
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "hubspot_list_contacts",
            "description": "List recent HubSpot contacts. Use this when user asks to see HubSpot contacts, check HubSpot account, or browse contacts. Returns up to 10 most recent contacts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of contacts to return (default 10, max 50)"
                    }
                }
            }
        },
        {
            "name": "hubspot_create_contact",
            "description": "Create a HubSpot contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {"type": "string"},
                    "firstName": {"type": "string"},
                    "lastName": {"type": "string"}
                },
                "required": ["email"]
            }
        },
        {
            "name": "hubspot_create_note",
            "description": "Create a HubSpot note associated with a contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contactId": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["contactId", "content"]
            }
        },
        {
            "name": "gmail_send",
            "description": "Send an email via Gmail. Use threadId to reply-in-thread when available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "threadId": {"type": "string"}
                },
                "required": ["to", "subject", "body"]
            }
        },
        {
            "name": "calendar_find_slots",
            "description": "Find 3 available time slots in the user's calendar within a given window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "durationMin": {"type": "number"},
                    "windowStart": {"type": "string"},
                    "windowEnd": {"type": "string"}
                },
                "required": ["durationMin", "windowStart", "windowEnd"]
            }
        },
        {
            "name": "calendar_create_event",
            "description": "Create a Google Calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["title", "start", "end", "attendees"]
            }
        },
        {
            "name": "calendar_list_events",
            "description": "List upcoming calendar events within a time window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeMin": {"type": "string", "description": "Start of time window (ISO format)"},
                    "timeMax": {"type": "string", "description": "End of time window (ISO format)"},
                    "maxResults": {"type": "number", "description": "Maximum number of events to return (default 10)"}
                },
                "required": ["timeMin", "timeMax"]
            }
        },
        {
            "name": "calendar_get_event",
            "description": "Get details of a specific calendar event by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "eventId": {"type": "string"}
                },
                "required": ["eventId"]
            }
        },
        {
            "name": "calendar_update_event",
            "description": "Update an existing calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "eventId": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["eventId"]
            }
        },
        {
            "name": "calendar_delete_event",
            "description": "Delete a calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "eventId": {"type": "string"}
                },
                "required": ["eventId"]
            }
        },
        {
            "name": "hubspot_get_contact_details",
            "description": "Get detailed information about a specific HubSpot contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contactId": {"type": "string"}
                },
                "required": ["contactId"]
            }
        },
        {
            "name": "hubspot_update_contact",
            "description": "Update an existing HubSpot contact's information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contactId": {"type": "string"},
                    "email": {"type": "string"},
                    "firstName": {"type": "string"},
                    "lastName": {"type": "string"},
                    "phone": {"type": "string"},
                    "company": {"type": "string"}
                },
                "required": ["contactId"]
            }
        },
        {
            "name": "task_list",
            "description": "List all tasks for the user, optionally filtered by status. IMPORTANT: When processing new emails or events, ALWAYS check waiting tasks to see if they're replies to pending workflows. This enables seamless task continuation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status: 'waiting' (awaiting external reply), 'pending' (in progress), 'done' (completed)"}
                }
            }
        },
        {
            "name": "task_save",
            "description": "Persist a multi-step task with status waiting for external reply or future processing. Save ALL context needed to resume: recipient email, thread ID, proposed options (times/dates), goal, contact IDs, etc. This enables seamless continuation when reply arrives.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Clear task title (e.g., 'Awaiting Sara Smith meeting reply')"},
                    "data": {"type": "object", "description": "Complete context: {recipient, threadId, proposedSlots, goal, contactId, etc.}"}
                },
                "required": ["title", "data"]
            }
        },
        {
            "name": "task_complete",
            "description": "Mark a task as done and store the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "result": {"type": "object"}
                },
                "required": ["id"]
            }
        },
        {
            "name": "instruction_create",
            "description": "Create an ongoing instruction that will be automatically executed by the background worker when relevant events occur (new emails, calendar events, HubSpot changes, etc.). Use this when the user asks to set up automated actions or rules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The instruction text describing what should happen automatically (e.g., 'When I receive an email, reply with Thank you', 'When I create a HubSpot contact, send them a welcome email')"
                    }
                },
                "required": ["content"]
            }
        }
    ]
}

class AgentRuntime:
    def __init__(self):
        logger.info("Initializing AgentRuntime...")
        self.google_service = GoogleService()
        self.hubspot_service = HubSpotService()
        self.rag_query = RAGQuery()
        logger.info("AgentRuntime initialized successfully")
    
    def _make_json_serializable(self, obj):
        """
        Recursively convert an object to be JSON serializable.
        Handles protobuf objects, RepeatedComposite, and other complex types.
        """
        # Handle None
        if obj is None:
            return None
        
        # Handle basic types
        if isinstance(obj, (str, int, float, bool)):
            return obj
        
        # Handle lists and tuples
        if isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        
        # Handle dicts
        if isinstance(obj, dict):
            return {key: self._make_json_serializable(value) for key, value in obj.items()}
        
        # Handle protobuf RepeatedComposite and similar
        if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, dict)):
            try:
                return [self._make_json_serializable(item) for item in obj]
            except:
                pass
        
        # Handle objects with _pb (protobuf)
        if hasattr(obj, '_pb'):
            return str(obj)
        
        # Handle objects with __dict__
        if hasattr(obj, '__dict__'):
            try:
                return {k: self._make_json_serializable(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
            except:
                return str(obj)
        
        # Fallback to string representation
        try:
            return str(obj)
        except:
            return None
    
    def get_active_instructions(self, user: User, db: Session) -> str:
        """Get active ongoing instructions for the user"""
        logger.debug(f"Getting active instructions for user {user.id}")
        
        instructions = db.query(Instruction).filter(
            Instruction.user_id == user.id,
            Instruction.is_active == True
        ).all()
        
        if not instructions:
            logger.debug(f"No active instructions found for user {user.id}")
            return "No active ongoing instructions."
        
        instruction_text = "ACTIVE ONGOING INSTRUCTIONS:\n"
        for i, instruction in enumerate(instructions, 1):
            instruction_text += f"{i}. {instruction.content}\n"
        
        logger.debug(f"Found {len(instructions)} active instructions for user {user.id}")
        return instruction_text
    
    def handle_tool_call(self, tool_name: str, arguments: Dict, user: User, db: Session) -> Dict:
        """Handle tool calls from the AI agent"""
        logger.info(f"Handling tool call: {tool_name} with arguments: {arguments}")
        
        try:
            if tool_name == "gmail_search":
                logger.info(f"Executing Gmail search for query: '{arguments['query']}'")
                # Search through emails using RAG query system
                docs = self.rag_query.search_documents(
                    user.id, 
                    arguments["query"], 
                    source="gmail",
                    limit=10,
                    db=db
                )
                result = {
                    "success": True, 
                    "emails": docs,
                    "count": len(docs),
                    "message": f"Found {len(docs)} emails matching '{arguments['query']}'"
                }
                logger.info(f"Gmail search completed: {len(docs)} results")
                return result
            
            elif tool_name == "hubspot_search_notes":
                logger.info(f"Executing HubSpot notes search for query: '{arguments['query']}'")
                # Search through HubSpot notes using RAG query system
                docs = self.rag_query.search_documents(
                    user.id,
                    arguments["query"],
                    source="hubspot_note",
                    limit=10,
                    db=db
                )
                result = {
                    "success": True,
                    "notes": docs,
                    "count": len(docs),
                    "message": f"Found {len(docs)} notes matching '{arguments['query']}'"
                }
                logger.info(f"HubSpot notes search completed: {len(docs)} results")
                return result
            
            elif tool_name == "hubspot_search_contact":
                logger.info(f"Executing HubSpot contact search for query: '{arguments['query']}'")
                contacts = self.hubspot_service.hs_search_contact(
                    user, arguments["query"], db
                )
                result = {"success": True, "contacts": contacts, "count": len(contacts)}
                logger.info(f"HubSpot contact search completed: {len(contacts)} results")
                return result
            
            elif tool_name == "hubspot_list_contacts":
                logger.info(f"Listing HubSpot contacts")
                limit = arguments.get("limit", 10)
                contacts = self.hubspot_service.hs_get_recent_contacts(user, limit=limit, db=db)
                result = {
                    "success": True,
                    "contacts": contacts,
                    "count": len(contacts),
                    "message": f"Found {len(contacts)} contacts in HubSpot"
                }
                logger.info(f"HubSpot contacts listed: {len(contacts)} contacts")
                return result
            
            elif tool_name == "hubspot_create_contact":
                logger.info(f"Creating HubSpot contact: {arguments['email']}")
                result = self.hubspot_service.hs_create_contact(
                    user, 
                    arguments["email"],
                    arguments.get("firstName"),
                    arguments.get("lastName"),
                    db
                )
                logger.info(f"HubSpot contact creation result: {result.get('success', False)}")
                return result
            
            elif tool_name == "hubspot_create_note":
                logger.info(f"Creating HubSpot note for contact: {arguments['contactId']}")
                result = self.hubspot_service.hs_create_note(
                    user,
                    arguments["contactId"],
                    arguments["content"],
                    db
                )
                logger.info(f"HubSpot note creation result: {result.get('success', False)}")
                return result
            
            elif tool_name == "gmail_send":
                logger.info(f"Sending Gmail to: {arguments['to']}, subject: {arguments['subject'][:50]}...")
                result = self.google_service.gmail_send(
                    user,
                    arguments["to"],
                    arguments["subject"],
                    arguments["body"],
                    arguments.get("threadId"),
                    db
                )
                logger.info(f"Gmail send result: {result.get('success', False)}")
                return result
            
            elif tool_name == "calendar_find_slots":
                logger.info(f"Finding calendar slots: duration={arguments['durationMin']}min, window={arguments['windowStart']} to {arguments['windowEnd']}")
                slots = self.google_service.calendar_find_slots(
                    user,
                    arguments["durationMin"],
                    arguments["windowStart"],
                    arguments["windowEnd"],
                    db
                )
                result = {"success": True, "slots": slots}
                logger.info(f"Calendar slots found: {len(slots)} slots")
                return result
            
            elif tool_name == "calendar_create_event":
                logger.info(f"Creating calendar event: {arguments['title']}")
                result = self.google_service.calendar_create_event(
                    user,
                    arguments["title"],
                    arguments["start"],
                    arguments["end"],
                    arguments["attendees"],
                    db
                )
                logger.info(f"Calendar event creation result: {result.get('success', False)}")
                return result
            
            elif tool_name == "calendar_list_events":
                logger.info(f"Listing calendar events: {arguments['timeMin']} to {arguments['timeMax']}")
                events = self.google_service.calendar_list_events(
                    user,
                    arguments["timeMin"],
                    arguments["timeMax"],
                    arguments.get("maxResults", 10),
                    db
                )
                result = {"success": True, "events": events, "count": len(events)}
                logger.info(f"Calendar events listed: {len(events)} events")
                return result
            
            elif tool_name == "calendar_get_event":
                logger.info(f"Getting calendar event: {arguments['eventId']}")
                result = self.google_service.calendar_get_event(
                    user,
                    arguments["eventId"],
                    db
                )
                logger.info(f"Calendar event get result: {result.get('success', False)}")
                return result
            
            elif tool_name == "calendar_update_event":
                logger.info(f"Updating calendar event: {arguments['eventId']}")
                result = self.google_service.calendar_update_event(
                    user,
                    arguments["eventId"],
                    arguments.get("title"),
                    arguments.get("start"),
                    arguments.get("end"),
                    arguments.get("attendees"),
                    db
                )
                logger.info(f"Calendar event update result: {result.get('success', False)}")
                return result
            
            elif tool_name == "calendar_delete_event":
                logger.info(f"Deleting calendar event: {arguments['eventId']}")
                result = self.google_service.calendar_delete_event(
                    user,
                    arguments["eventId"],
                    db
                )
                logger.info(f"Calendar event deletion result: {result.get('success', False)}")
                return result
            
            elif tool_name == "hubspot_get_contact_details":
                logger.info(f"Getting HubSpot contact details: {arguments['contactId']}")
                result = self.hubspot_service.hs_get_contact_details(
                    user,
                    arguments["contactId"],
                    db
                )
                logger.info(f"HubSpot contact details result: {result.get('success', False)}")
                return result
            
            elif tool_name == "hubspot_update_contact":
                logger.info(f"Updating HubSpot contact: {arguments['contactId']}")
                result = self.hubspot_service.hs_update_contact(
                    user,
                    arguments["contactId"],
                    arguments.get("email"),
                    arguments.get("firstName"),
                    arguments.get("lastName"),
                    arguments.get("phone"),
                    arguments.get("company"),
                    db
                )
                logger.info(f"HubSpot contact update result: {result.get('success', False)}")
                return result
            
            elif tool_name == "task_list":
                logger.info(f"Listing tasks for user {user.id}")
                status_filter = arguments.get("status")
                query = db.query(Task).filter(Task.user_id == user.id)
                if status_filter:
                    query = query.filter(Task.status == status_filter)
                tasks = query.all()
                
                task_list = []
                for task in tasks:
                    task_list.append({
                        "id": task.id,
                        "title": task.title,
                        "status": task.status,
                        "data": task.data,
                        "created_at": task.created_at.isoformat() if task.created_at else None,
                        "updated_at": task.updated_at.isoformat() if task.updated_at else None
                    })
                
                result = {"success": True, "tasks": task_list, "count": len(task_list)}
                logger.info(f"Tasks listed: {len(task_list)} tasks")
                return result
            
            elif tool_name == "task_save":
                logger.info(f"Saving task: {arguments['title']}")
                task = Task(
                    user_id=user.id,
                    title=arguments["title"],
                    status="waiting",
                    data=arguments["data"]
                )
                db.add(task)
                db.commit()
                result = {"success": True, "task_id": task.id}
                logger.info(f"Task saved with ID: {task.id}")
                return result
            
            elif tool_name == "task_complete":
                logger.info(f"Completing task: {arguments['id']}")
                task = db.query(Task).filter(
                    Task.id == arguments["id"],
                    Task.user_id == user.id
                ).first()
                
                if task:
                    task.status = "done"
                    if "result" in arguments:
                        task.data = {**(task.data or {}), "result": arguments["result"]}
                    db.commit()
                    result = {"success": True, "task_id": task.id}
                    logger.info(f"Task {task.id} completed successfully")
                    return result
                else:
                    logger.warning(f"Task {arguments['id']} not found for user {user.id}")
                    return {"success": False, "error": "Task not found"}
            
            elif tool_name == "instruction_create":
                logger.info(f"Creating instruction: {arguments['content'][:100]}")
                from models_temp import Instruction
                
                instruction = Instruction(
                    user_id=user.id,
                    content=arguments["content"],
                    is_active=True
                )
                db.add(instruction)
                db.commit()
                db.refresh(instruction)
                
                logger.info(f"Instruction created with ID: {instruction.id}")
                return {
                    "success": True,
                    "instruction_id": instruction.id,
                    "content": instruction.content,
                    "is_active": instruction.is_active,
                    "message": "Instruction created successfully and is now active. The background worker will monitor for relevant events and execute this instruction automatically."
                }
            
            else:
                logger.warning(f"Unknown tool called: {tool_name}")
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
                
        except Exception as e:
            logger.error(f"Error handling tool call {tool_name}: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_chat_history(self, user: User, db: Session, limit: int = 20) -> List[Dict]:
        """Get recent chat history for context"""
        logger.debug(f"Retrieving chat history for user {user.id}, limit: {limit}")
        
        # Get recent messages from database, ordered by creation time
        # Filter out proactive evaluation messages and empty content messages
        recent_messages = db.query(Message).filter(
            Message.user_id == user.id,
            Message.role.in_(['user', 'assistant']),  # Only user and assistant messages, not tool messages
            Message.content.isnot(None),  # Exclude None content
            Message.content != "",  # Exclude empty content
            ~Message.content.like("PROACTIVE EVENT EVALUATION%")  # Exclude proactive evaluation messages
        ).order_by(Message.created_at.desc()).limit(limit).all()
        
        # Reverse to get chronological order (oldest first)
        recent_messages = list(reversed(recent_messages))
        
        logger.debug(f"Retrieved {len(recent_messages)} messages from history")
        
        # Convert to Gemini format
        history = []
        for msg in recent_messages:
            # Map database role to Gemini role
            gemini_role = "model" if msg.role == "assistant" else "user"
            history.append({
                "role": gemini_role,
                "parts": [msg.content] if msg.content else [""]
            })
        
        return history
    
    def process_message(self, user: User, message: str, db: Session, task_context: Optional[Dict] = None) -> Dict:
        """Process a user message and return AI response with tool calls"""
        logger.info(f"Processing message for user {user.id}: {message[:100]}...")
        
        try:
            # Get RAG context
            logger.debug("Building RAG context...")
            rag_context = self.rag_query.build_context(user.id, message, db=db)
            logger.debug(f"RAG context length: {len(rag_context)} characters")
            
            # Get active instructions
            logger.debug("Getting active instructions...")
            instructions = self.get_active_instructions(user, db)
            logger.debug(f"Instructions length: {len(instructions)} characters")
            
            # Get chat history
            logger.debug("Retrieving chat history...")
            chat_history = self.get_chat_history(user, db, limit=20)
            logger.debug(f"Chat history contains {len(chat_history)} messages")
            
            # Build messages for Gemini
            logger.debug("Building Gemini messages...")
            
            # Add current date/time for temporal calculations
            from datetime import datetime
            current_datetime = datetime.now().isoformat()
            current_date_readable = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
            
            system_content = SYSTEM_PROMPT + f"\n{instructions}" + f"\n\nCURRENT DATE/TIME: {current_date_readable} (ISO: {current_datetime})\nUse this to calculate relative dates like 'tomorrow', 'next week', etc.\n\nRAG CONTEXT:\n{rag_context}"
            if task_context:
                logger.info(f"Adding task context: {task_context}")
                system_content += f"\nTASK CONTEXT (resuming task):\n{json.dumps(task_context, indent=2)}"

            messages = [
                {"role": "user", "parts": [system_content]},
                {"role": "model", "parts": ["Understood. I will act as the AI Agent for a Financial Advisor with access to Gmail, Google Calendar, and HubSpot tools."]},
            ]
            
            # Add chat history for context
            messages.extend(chat_history)
            
            # Add current user message
            messages.append({"role": "user", "parts": [message]})
            
            logger.debug(f"Built {len(messages)} messages for Gemini")
            
            # Store user message
            logger.debug("Storing user message in database...")
            user_msg = Message(
                user_id=user.id,
                role="user",
                content=message
            )
            db.add(user_msg)
            db.commit()
            logger.debug(f"User message stored with ID: {user_msg.id}")
            
            # Log messages before calling Gemini (first call)
            logger.info("=" * 80)
            logger.info("CALLING GEMINI API (Initial Call)")
            logger.info(f"Number of messages: {len(messages)}")
            for i, msg in enumerate(messages):
                logger.info(f"Message {i+1}: role={msg.get('role')}, parts_count={len(msg.get('parts', []))}")
                if msg.get('role') == 'user' and i == len(messages) - 1:  # Log last user message
                    logger.info(f"User query: {message[:200]}...")
            logger.info("=" * 80)
            
            # Multi-round tool calling loop - continue until no more tool calls
            logger.info("Starting multi-round tool calling loop...")
            model = genai.GenerativeModel('gemini-2.5-flash-lite')
            all_tool_results = []
            round_num = 0
            max_rounds = 10  # Safety limit to prevent infinite loops
            
            while round_num < max_rounds:
                round_num += 1
                logger.info(f"=" * 80)
                logger.info(f"TOOL CALLING ROUND {round_num}")
                logger.info(f"=" * 80)
                
                # Call Gemini with function calling
                logger.info(f"Calling Gemini API (Round {round_num})...")
                response = model.generate_content(
                    messages,
                    tools=TOOLS,
                    generation_config=genai.GenerationConfig(
                        temperature=0.2
                    )
                )
                logger.info("Gemini API call completed successfully")

                assistant_message = response.candidates[0].content
                logger.debug("Processing assistant message...")
                
                # Extract tool calls from response
                tool_calls = []
                if hasattr(assistant_message, 'parts'):
                    logger.debug(f"Assistant message has {len(assistant_message.parts)} parts")
                    for part in assistant_message.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            logger.info(f"Found tool call: {part.function_call.name}")
                            tool_calls.append(type('ToolCall', (), {
                                'function': type('Function', (), {
                                    'name': part.function_call.name,
                                    'arguments': json.dumps(dict(part.function_call.args))
                                })()
                            })())
                
                logger.info(f"Round {round_num}: Found {len(tool_calls)} tool calls")
                
                # Extract text content if any
                assistant_content = ""
                if hasattr(assistant_message, 'parts'):
                    for part in assistant_message.parts:
                        if hasattr(part, 'text') and part.text:
                            assistant_content += part.text
                
                # If no tool calls, we're done - this is the final response
                if not tool_calls:
                    logger.info(f"No tool calls in round {round_num}. Ending tool calling loop.")
                    
                    # Store final assistant message with text
                    logger.debug("Storing final assistant message...")
                    final_assistant_msg = Message(
                        user_id=user.id,
                        role="assistant",
                        content=assistant_content
                    )
                    db.add(final_assistant_msg)
                    db.commit()
                    logger.debug(f"Final assistant message stored with ID: {final_assistant_msg.id}")
                    break
                
                # We have tool calls - execute them
                logger.info(f"Processing {len(tool_calls)} tool calls in round {round_num}...")
                
                # Add assistant's response with function calls to messages
                messages.append({"role": "model", "parts": assistant_message.parts})
                
                # Store assistant message (may be empty if only tool calls)
                if assistant_content or round_num == 1:  # Always store first message
                    assistant_msg = Message(
                        user_id=user.id,
                        role="assistant",
                        content=assistant_content or ""
                    )
                    db.add(assistant_msg)
                    db.commit()
                
                # Execute each tool call
                round_tool_results = []
                for i, tool_call in enumerate(tool_calls):
                    tool_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    logger.info(f"Executing tool {i+1}/{len(tool_calls)}: {tool_name}")
                    logger.info(f"Arguments: {json.dumps(arguments, indent=2)}")
                    
                    # Store tool call message
                    tool_msg = Message(
                        user_id=user.id,
                        role="tool",
                        content=f"Tool: {tool_name}\nArguments: {json.dumps(arguments, indent=2)}"
                    )
                    db.add(tool_msg)
                    
                    # Execute tool
                    result = self.handle_tool_call(tool_name, arguments, user, db)
                    logger.info(f"Tool {tool_name} completed: success={result.get('success', False)}")
                    
                    tool_result = {
                        "tool": tool_name,
                        "arguments": arguments,
                        "result": result
                    }
                    round_tool_results.append(tool_result)
                    all_tool_results.append(tool_result)
                    
                    # Store tool result message
                    # Make result JSON serializable before dumping
                    serializable_result = self._make_json_serializable(result)
                    result_msg = Message(
                        user_id=user.id,
                        role="tool",
                        content=f"Result: {json.dumps(serializable_result, indent=2)}"
                    )
                    db.add(result_msg)
                    
                    # Add function response to messages for next round
                    result_data = self._make_json_serializable(result)
                    
                    function_response_part = genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=tool_call.function.name,
                            response=result_data
                        )
                    )
                    messages.append({
                        "role": "function",
                        "parts": [function_response_part]
                    })
                
                db.commit()
                logger.info(f"Round {round_num}: All {len(tool_calls)} tool calls executed. Continuing to next round...")
            
            # If we hit max rounds, log a warning
            if round_num >= max_rounds:
                logger.warning(f"Hit maximum tool calling rounds ({max_rounds}). Forcing termination.")
                assistant_content = "I've completed multiple steps but reached the maximum number of tool calls. Please review the actions taken."
            
            logger.info(f"Tool calling loop completed after {round_num} rounds")
            logger.info(f"Total tool calls made: {len(all_tool_results)}")
            
            final_result = {
                "success": True,
                "response": assistant_content,
                "tool_calls": all_tool_results
            }
            
            logger.info(f"Message processing completed successfully. Response length: {len(assistant_content)} characters")
            return final_result
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "response": "I apologize, but I encountered an error processing your request."
            }
    
    def resume_task(self, task: Task, db: Session) -> Dict:
        """Resume a waiting task with new context"""
        logger.info(f"Resuming task {task.id}: {task.title}")
        
        if task.status != "waiting":
            logger.warning(f"Task {task.id} is not in waiting status: {task.status}")
            return {"success": False, "error": "Task is not in waiting status"}
        
        # Update task status and last run time
        logger.debug(f"Updating task {task.id} status to pending")
        task.status = "pending"
        task.last_run_at = datetime.utcnow()
        db.commit()
        
        # Process the task with its stored context
        context_message = f"Resuming task: {task.title}\nContext: {json.dumps(task.data, indent=2)}"
        logger.info(f"Processing task context: {task.data}")
        
        result = self.process_message(task.user, context_message, db, task.data)
        logger.info(f"Task {task.id} processing completed: {result.get('success', False)}")
        
        return result
