from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database_temp import get_db, create_tables
from models_temp import User, Account, Instruction, Task, Message, Doc, WebhookSubscription, WebhookEvent, SyncState
from services.google import GoogleService
from services.hubspot import HubSpotService
from services.webhooks import WebhookHandler
from agent.runtime import AgentRuntime, SYSTEM_PROMPT, TOOLS
from rag.ingest import RAGIngester
from config import settings
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime
import json
import threading
import uuid
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Financial Advisor AI Agent", version="1.0.0")

# Set up static directory path
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins since frontend is served from same backend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
google_service = GoogleService()
hubspot_service = HubSpotService()
agent_runtime = AgentRuntime()
rag_ingester = RAGIngester()
webhook_handler = WebhookHandler()

# Proactive worker instance
proactive_worker = None

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Start the proactive worker on app startup"""
    global proactive_worker
    
    try:
        logger.info("Starting proactive worker...")
        from worker_proactive import ProactiveWorker
        
        proactive_worker = ProactiveWorker()
        
        # Start worker in background thread
        worker_thread = threading.Thread(
            target=proactive_worker.start,
            daemon=True,  # Dies when main process dies
            name="ProactiveWorker"
        )
        worker_thread.start()
        
        logger.info("Proactive worker started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start proactive worker: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(traceback.format_exc())

@app.on_event("shutdown")
async def shutdown_event():
    """Stop the proactive worker on app shutdown"""
    global proactive_worker
    
    if proactive_worker:
        try:
            logger.info("Stopping proactive worker...")
            proactive_worker.stop()
            logger.info("Proactive worker stopped")
        except Exception as e:
            logger.error(f"Error stopping proactive worker: {e}")

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

manager = ConnectionManager()

# Store active ingestion jobs
active_ingestions = {}

def get_db_for_thread():
    """Get database session for background threads"""
    from database_temp import SessionLocal
    return SessionLocal()

async def send_progress_update(job_id: str, message: str, current: int, total: int):
    """Send progress update via WebSocket"""
    try:
        progress_data = {
            "type": "ingestion_progress",
            "job_id": job_id,
            "message": message,
            "progress": {
                "current": current,
                "total": total,
                "percentage": int((current / total) * 100) if total > 0 else 0
            }
        }
        
        # Send to all connected clients (in production, you'd filter by user)
        for connection in manager.active_connections:
            try:
                await connection.send_json(progress_data)
            except Exception as e:
                logger.error(f"Error sending progress update: {e}")
                
    except Exception as e:
        logger.error(f"Error in send_progress_update: {e}")

def run_background_ingestion(user_id: str, job_id: str):
    """Run ingestion in background thread"""
    db = get_db_for_thread()
    try:
        logger.info(f"Starting background ingestion job {job_id} for user {user_id}")
        
        # Get user from database
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for background ingestion")
            active_ingestions[job_id]["status"] = "failed"
            active_ingestions[job_id]["error"] = "User not found"
            return
        
        # Update job status
        active_ingestions[job_id]["status"] = "running"
        active_ingestions[job_id]["progress"] = {"current": 0, "total": 2, "step": "Starting ingestion..."}
        
        results = {
            "gmail": {"status": "not_attempted", "count": 0, "error": None},
            "hubspot": {"status": "not_attempted", "count": 0, "error": None}
        }
        
        # Check if Google account exists
        google_account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'google'
        ).first()
        
        # Ingest Gmail data if connected
        if google_account:
            try:
                logger.info(f"Starting Gmail ingestion for user {user.id}")
                active_ingestions[job_id]["progress"] = {"current": 1, "total": 2, "step": "Processing Gmail messages..."}
                
                gmail_result = rag_ingester.ingest_gmail_initial(user, db)
                
                # Count imported emails
                email_count = db.query(Doc).filter(
                    Doc.user_id == user.id,
                    Doc.source == 'gmail'
                ).count()
                
                results["gmail"] = {
                    "status": "success",
                    "count": email_count,
                    "processed": gmail_result.get("processed", 0) if gmail_result else 0,
                    "errors": gmail_result.get("errors", 0) if gmail_result else 0,
                    "skipped": gmail_result.get("skipped", 0) if gmail_result else 0,
                    "error": None
                }
                logger.info(f"Gmail ingestion completed: {email_count} emails")
            except Exception as e:
                logger.error(f"Gmail ingestion error: {e}")
                results["gmail"] = {
                    "status": "failed",
                    "count": 0,
                    "error": str(e)
                }
        else:
            results["gmail"] = {
                "status": "not_connected",
                "count": 0,
                "error": "Google account not connected"
            }
        
        # Check if HubSpot account exists
        hubspot_account = db.query(Account).filter(
            Account.user_id == user.id,
            Account.provider == 'hubspot'
        ).first()
        
        # Ingest HubSpot data if connected
        if hubspot_account:
            try:
                logger.info(f"Starting HubSpot ingestion for user {user.id}")
                active_ingestions[job_id]["progress"] = {"current": 2, "total": 2, "step": "Processing HubSpot data..."}
                
                hubspot_result = rag_ingester.ingest_hubspot_initial(user, db)
                
                # Count imported contacts and notes
                contact_count = db.query(Doc).filter(
                    Doc.user_id == user.id,
                    Doc.source == 'hubspot_contact'
                ).count()
                note_count = db.query(Doc).filter(
                    Doc.user_id == user.id,
                    Doc.source == 'hubspot_note'
                ).count()
                
                results["hubspot"] = {
                    "status": "success",
                    "count": contact_count + note_count,
                    "contacts": contact_count,
                    "notes": note_count,
                    "processed": hubspot_result.get("total_processed", 0) if hubspot_result else 0,
                    "errors": hubspot_result.get("total_errors", 0) if hubspot_result else 0,
                    "details": hubspot_result.get("details", {}) if hubspot_result else {},
                    "error": None
                }
                logger.info(f"HubSpot ingestion completed: {contact_count} contacts, {note_count} notes")
            except Exception as e:
                logger.error(f"HubSpot ingestion error: {e}")
                results["hubspot"] = {
                    "status": "failed",
                    "count": 0,
                    "error": str(e)
                }
        else:
            results["hubspot"] = {
                "status": "not_connected",
                "count": 0,
                "error": "HubSpot account not connected"
            }
        
        # Update job with results
        active_ingestions[job_id]["status"] = "completed"
        active_ingestions[job_id]["results"] = results
        active_ingestions[job_id]["completed_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Background ingestion job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Background ingestion job {job_id} failed: {e}")
        active_ingestions[job_id]["status"] = "failed"
        active_ingestions[job_id]["error"] = str(e)
    finally:
        db.close()

# Create tables on startup
@app.on_event("startup")
async def startup_event_db():
    create_tables()
    logger.info("Database tables created")

# Pydantic models
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    success: bool
    response: str
    tool_calls: Optional[List[Dict]] = None
    error: Optional[str] = None

class InstructionRequest(BaseModel):
    content: str

class InstructionResponse(BaseModel):
    id: str
    content: str
    is_active: bool
    created_at: str

class TaskResponse(BaseModel):
    id: str
    title: str
    status: str
    data: Optional[Dict] = None
    created_at: str
    updated_at: str

class ConnectionResponse(BaseModel):
    gmail: bool
    hubspot: bool

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    google_email: Optional[str] = None

# Authentication helpers
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Get current user from session cookie"""
    logger.debug("Getting current user from session")
    
    # For now, we'll use a simple session approach
    # In production, you'd want proper session management
    user_id = request.cookies.get("user_id")
    if not user_id:
        logger.warning("No user_id cookie found in request")
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    logger.debug(f"Found user_id cookie: {user_id}")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning(f"User not found for user_id: {user_id}")
        raise HTTPException(status_code=401, detail="User not found")
    
    logger.debug(f"Authenticated user: {user.email}")
    return user

def get_db_for_thread():
    """Get a new database session for background threads"""
    from database_temp import SessionLocal
    return SessionLocal()

def make_json_serializable(obj):
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
        return [make_json_serializable(item) for item in obj]
    
    # Handle dicts
    if isinstance(obj, dict):
        return {key: make_json_serializable(value) for key, value in obj.items()}
    
    # Handle protobuf RepeatedComposite and similar
    if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, dict)):
        try:
            return [make_json_serializable(item) for item in obj]
        except:
            pass
    
    # Handle objects with _pb (protobuf)
    if hasattr(obj, '_pb'):
        return str(obj)
    
    # Handle objects with __dict__
    if hasattr(obj, '__dict__'):
        try:
            return {k: make_json_serializable(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
        except:
            return str(obj)
    
    # Fallback to string representation
    try:
        return str(obj)
    except:
        return None

# Health check
@app.get("/health")
async def health_check():
    return {"ok": True}

# Auth status check (for debugging)
@app.get("/auth/status")
async def auth_status(request: Request, db: Session = Depends(get_db)):
    """Check if user is authenticated"""
    logger.info("Checking authentication status")
    
    user_id = request.cookies.get("user_id")
    if not user_id:
        logger.info("No user_id cookie found - not authenticated")
        return {
            "authenticated": False,
            "cookie_present": False,
            "message": "No user_id cookie found"
        }
    
    logger.debug(f"Found user_id cookie: {user_id}")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning(f"User not found for user_id: {user_id}")
        return {
            "authenticated": False,
            "cookie_present": True,
            "user_id": user_id,
            "message": "User not found in database"
        }
    
    # Get connections
    logger.debug("Checking user connections")
    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    providers = {acc.provider for acc in accounts}
    
    logger.info(f"User {user.email} authenticated with connections: {providers}")
    
    return {
        "authenticated": True,
        "cookie_present": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name
        },
        "connections": {
            "google": "google" in providers,
            "hubspot": "hubspot" in providers
        }
    }

# OAuth configuration check
@app.get("/auth/config-check")
async def oauth_config_check():
    """Check OAuth configuration for debugging"""
    return {
        "google_client_id_set": bool(settings.GOOGLE_CLIENT_ID),
        "google_client_secret_set": bool(settings.GOOGLE_CLIENT_SECRET),
        "google_redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "google_scopes": settings.GOOGLE_SCOPES.split(),
        "hubspot_client_id_set": bool(settings.HUBSPOT_CLIENT_ID),
        "hubspot_client_secret_set": bool(settings.HUBSPOT_CLIENT_SECRET),
        "hubspot_redirect_uri": settings.HUBSPOT_REDIRECT_URI
    }

# Root route - serve frontend
@app.get("/")
async def serve_root():
    """Serve frontend for root route"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    else:
        raise HTTPException(status_code=404, detail="Frontend not built")

# App dashboard route
@app.get("/app")
async def serve_app():
    """Serve frontend for app dashboard"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    else:
        raise HTTPException(status_code=404, detail="Frontend not built")


# Authentication endpoints
@app.get("/auth/google/login")
async def google_login():
    """Start Google OAuth flow"""
    logger.info("Starting Google OAuth login flow")
    
    try:
        auth_url, state = google_service.get_authorization_url()
        # In production, you'd store the state in session/database
        # For now, we'll use a simple approach
        logger.info(f"Generated OAuth state: {state}")
        logger.info(f"Redirecting to Google OAuth URL")
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Error starting Google OAuth: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to start Google OAuth")

@app.get("/auth/google/callback")
async def google_callback(
    code: str,
    state: str = None,
    scope: str = None,
    authuser: str = None,
    prompt: str = None,
    db: Session = Depends(get_db)
):
    """Handle Google OAuth callback"""
    logger.info(f"Google OAuth callback received - Code: {code[:10]}..., State: {state}")
    
    try:
        if scope:
            logger.info(f"Scope parameter received: {scope}")

        logger.debug("Processing Google OAuth callback...")
        user, success = google_service.handle_callback(code, state, db)
        
        if success and user:
            logger.info(f"Google OAuth successful for user: {user.email}")
            
            # Trigger initial data ingestion automatically in background
            try:
                # Check if this is first time connecting (no docs yet)
                existing_docs = db.query(Doc).filter(
                    Doc.user_id == user.id,
                    Doc.source == 'gmail'
                ).count()
                
                if existing_docs == 0:
                    logger.info(f"First time Google connection for user {user.id} - starting initial ingestion")
                    # Run ingestion in background (non-blocking)
                    import threading
                    def run_ingestion():
                        db_local = get_db_for_thread()
                        try:
                            rag_ingester.ingest_gmail_initial(user, db_local)
                            logger.info(f"Background Gmail ingestion completed for user {user.id}")
                        except Exception as e:
                            logger.error(f"Background Gmail ingestion failed: {e}")
                        finally:
                            db_local.close()
                    
                    thread = threading.Thread(target=run_ingestion)
                    thread.daemon = True
                    thread.start()
                else:
                    logger.info(f"User {user.id} already has {existing_docs} Gmail docs, skipping initial ingestion")
            except Exception as e:
                logger.error(f"Failed to start background ingestion: {e}")
            
            # Set session cookie and redirect to app
            logger.info(f"Setting session cookie and redirecting user {user.id} to /")
            response = RedirectResponse(url="/")  # Redirect to dashboard
            response.set_cookie(
                key="user_id",
                value=user.id,
                path="/",
                httponly=False,  # Set to False to allow JS access for debugging
                secure=True,  # Set to True for production HTTPS
                samesite="lax",
                max_age=86400 * 30  # 30 days
            )
            return response
        else:
            logger.error("Google OAuth failed - no user returned or success=False")
            # Redirect to error page instead of throwing 400
            return RedirectResponse(url="/?error=oauth_failed")
    except Exception as e:
        logger.error(f"Google OAuth error: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        # Redirect to error page instead of throwing 400
        return RedirectResponse(url="/?error=oauth_error")

@app.get("/auth/hubspot/login")
async def hubspot_login():
    """Start HubSpot OAuth flow"""
    logger.info("Starting HubSpot OAuth login flow")
    
    try:
        auth_url = hubspot_service.get_authorization_url()
        logger.info(f"Redirecting to HubSpot OAuth URL")
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Error starting HubSpot OAuth: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to start HubSpot OAuth")

@app.get("/auth/hubspot/callback")
async def hubspot_callback(code: str, request: Request, db: Session = Depends(get_db)):
    """Handle HubSpot OAuth callback"""
    logger.info(f"HubSpot OAuth callback received - Code: {code[:10]}...")
    
    try:
        # Try to get existing authenticated user from cookie
        existing_user_id = request.cookies.get("user_id")
        if existing_user_id:
            logger.info(f"Found existing user session: {existing_user_id}")
        else:
            logger.info("No existing user session found")
        
        logger.debug("Processing HubSpot OAuth callback...")
        user, success = hubspot_service.handle_callback(code, db, existing_user_id)
        
        if success and user:
            logger.info(f"HubSpot OAuth successful for user: {user.email}")
            
            # Trigger initial data ingestion automatically in background
            try:
                # Check if this is first time connecting (no docs yet)
                existing_docs = db.query(Doc).filter(
                    Doc.user_id == user.id,
                    Doc.source.in_(['hubspot_contact', 'hubspot_note'])
                ).count()
                
                if existing_docs == 0:
                    logger.info(f"First time HubSpot connection for user {user.id} - starting initial ingestion")
                    # Run ingestion in background (non-blocking)
                    import threading
                    def run_ingestion():
                        db_local = get_db_for_thread()
                        try:
                            rag_ingester.ingest_hubspot_initial(user, db_local)
                            logger.info(f"Background HubSpot ingestion completed for user {user.id}")
                        except Exception as e:
                            logger.error(f"Background HubSpot ingestion failed: {e}")
                        finally:
                            db_local.close()
                    
                    thread = threading.Thread(target=run_ingestion)
                    thread.daemon = True
                    thread.start()
                else:
                    logger.info(f"User {user.id} already has {existing_docs} HubSpot docs, skipping initial ingestion")
            except Exception as e:
                logger.error(f"Failed to start background ingestion: {e}")
            
            # Set session cookie and redirect to app
            logger.info(f"Setting session cookie and redirecting user {user.id} to /")
            response = RedirectResponse(url="/")  # Redirect to dashboard
            response.set_cookie(
                key="user_id",
                value=user.id,
                path="/",
                httponly=False,  # Set to False to allow JS access for debugging
                secure=True,  # Set to True for production HTTPS
                samesite="lax",
                max_age=86400 * 30  # 30 days
            )
            return response
        else:
            logger.error("HubSpot OAuth failed - no user returned or success=False")
            return RedirectResponse(url="/?error=oauth_failed")
    except Exception as e:
        logger.error(f"HubSpot OAuth error: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error details: {str(e)}")
        return RedirectResponse(url="/?error=oauth_error")

# User endpoints
@app.get("/me", response_model=UserResponse)
async def get_current_user_info(user: User = Depends(get_current_user)):
    """Get current user information"""
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        google_email=user.google_email
    )

@app.get("/me/connections", response_model=ConnectionResponse)
async def get_connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get connection status for user - validates actual scopes granted"""
    # Check if Google account exists AND has required scopes (Gmail + Calendar)
    gmail_connected = google_service.has_gmail_scope(user, db) and google_service.has_calendar_scope(user, db)
    
    # Check if HubSpot account exists AND is working
    hubspot_connected = hubspot_service.is_connected(user, db)
    
    return ConnectionResponse(
        gmail=gmail_connected,  # Represents both Gmail and Calendar
        hubspot=hubspot_connected
    )

# WebSocket chat endpoint for streaming - Connection-level auth
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, db: Session = Depends(get_db)):
    """WebSocket endpoint for streaming chat with tool call updates"""
    await manager.connect(websocket)
    
    try:
        # Get user_id from query parameters (connection-level auth)
        user_id = websocket.query_params.get("user_id")
        
        if not user_id:
            await manager.send_personal_message({
                "type": "error",
                "content": "User ID required in connection URL"
            }, websocket)
            return
        
        # Get user from database
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await manager.send_personal_message({
                "type": "error", 
                "content": "User not found"
            }, websocket)
            return
        
        # Send chat history on initial connection
        chat_history = agent_runtime.get_chat_history(user, db, limit=50)
        if chat_history:
            # Convert chat history to frontend format
            history_messages = []
            for msg in chat_history:
                if msg["role"] in ["user", "model"]:
                    history_messages.append({
                        "role": "assistant" if msg["role"] == "model" else msg["role"],
                        "content": msg["parts"][0] if isinstance(msg["parts"], list) else msg["parts"]
                    })
            
            await manager.send_personal_message({
                "type": "chat_history",
                "messages": history_messages
            }, websocket)
        
        # Process multiple messages per connection
        while True:
            try:
                data = await websocket.receive_json()
                message = data.get("message", "")
                
                if not message:
                    continue
                
                # Send initial response
                await manager.send_personal_message({
                    "type": "assistant_start",
                    "content": "Thinking..."
                }, websocket)
                
                try:
                    # Process message with streaming updates
                    await process_message_with_streaming(user, message, db, websocket)
                    
                except Exception as e:
                    logger.error(f"WebSocket chat error: {e}")
                    await manager.send_personal_message({
                        "type": "error",
                        "content": f"I encountered an error: {str(e)}"
                    }, websocket)
                    
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                await manager.send_personal_message({
                    "type": "error",
                    "content": "I encountered an error processing your request."
                }, websocket)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

async def process_message_with_streaming(user: User, message: str, db: Session, websocket: WebSocket):
    """Process message with streaming updates for tool calls"""
    logger.info(f"Processing streaming message for user {user.id}: {message[:100]}...")
    
    try:
        # Get RAG context
        logger.debug("Building RAG context...")
        rag_context = agent_runtime.rag_query.build_context(user.id, message, db=db)
        logger.debug(f"RAG context length: {len(rag_context)} characters")
        
        # Get active instructions
        logger.debug("Getting active instructions...")
        instructions = agent_runtime.get_active_instructions(user, db)
        logger.debug(f"Instructions length: {len(instructions)} characters")
        
        # Get chat history
        logger.debug("Retrieving chat history...")
        chat_history = agent_runtime.get_chat_history(user, db, limit=20)
        logger.debug(f"Chat history contains {len(chat_history)} messages")
        
        # Build messages for Gemini
        logger.debug("Building Gemini messages...")
        
        # Add current date/time for temporal calculations
        current_datetime = datetime.utcnow().isoformat()
        current_date_readable = datetime.utcnow().strftime("%A, %B %d, %Y at %I:%M %p UTC")
        
        system_content = SYSTEM_PROMPT + f"\n{instructions}" + f"\n\nCURRENT DATE/TIME: {current_date_readable} (ISO: {current_datetime})\nUse this to calculate relative dates like 'tomorrow', 'next week', etc.\n\nRAG CONTEXT:\n{rag_context}"
        
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
        logger.info("CALLING GEMINI API (Initial Call) - WebSocket")
        logger.info(f"Number of messages: {len(messages)}")
        for i, msg in enumerate(messages):
            logger.info(f"Message {i+1}: role={msg.get('role')}, parts_count={len(msg.get('parts', []))}")
            if msg.get('role') == 'user' and i == len(messages) - 1:  # Log last user message
                logger.info(f"User query: {message[:200]}...")
        logger.info("=" * 80)
        
        # Call Gemini with function calling
        logger.info("Calling Gemini API...")
        import google.generativeai as genai
        from agent.runtime import TOOLS
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
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
        
        logger.info(f"Found {len(tool_calls)} tool calls")
        
        # Store assistant message
        logger.debug("Storing assistant message...")
        assistant_content = ""
        if hasattr(assistant_message, 'parts'):
            for part in assistant_message.parts:
                if hasattr(part, 'text') and part.text:
                    assistant_content += part.text

        assistant_msg = Message(
            user_id=user.id,
            role="assistant",
            content=assistant_content or ""
        )
        db.add(assistant_msg)
        db.commit()
        logger.debug(f"Assistant message stored with ID: {assistant_msg.id}")
        
        # Handle tool calls with streaming updates
        if tool_calls:
            await manager.send_personal_message({
                "type": "tool_calls_start",
                "content": f"Executing {len(tool_calls)} tool(s)..."
            }, websocket)
            
            logger.info(f"Processing {len(tool_calls)} tool calls...")
            tool_results = []
            for i, tool_call in enumerate(tool_calls):
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                logger.info(f"Processing tool call {i+1}/{len(tool_calls)}: {tool_name}")
                
                # Send tool call update
                await manager.send_personal_message({
                    "type": "tool_call",
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": "executing"
                }, websocket)
                
                # Store tool call message
                tool_msg = Message(
                    user_id=user.id,
                    role="tool",
                    content=f"Tool: {tool_name}\nArguments: {json.dumps(arguments, indent=2)}"
                )
                db.add(tool_msg)
                
                # Execute tool
                logger.debug(f"Executing tool: {tool_name}")
                result = agent_runtime.handle_tool_call(tool_name, arguments, user, db)
                logger.info(f"Tool {tool_name} execution completed: {result.get('success', False)}")
                
                tool_results.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result
                })
                
                # Send tool result update
                await manager.send_personal_message({
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": make_json_serializable(result),
                    "status": "completed"
                }, websocket)
                
                # Store tool result message
                logger.debug(f"Storing tool result for {tool_name}")
                serializable_result = make_json_serializable(result)
                result_msg = Message(
                    user_id=user.id,
                    role="tool",
                    content=f"Result: {json.dumps(serializable_result, indent=2)}"
                )
                db.add(result_msg)
            
            db.commit()
            logger.info(f"All {len(tool_calls)} tool calls processed successfully")
            
            # Send tool calls completion
            await manager.send_personal_message({
                "type": "tool_calls_complete",
                "content": "Processing results..."
            }, websocket)
            
            # Send tool results back to Gemini for processing
            logger.info("Sending tool results back to Gemini for processing...")
            
            # First, add the assistant's response with function calls to messages
            messages.append({"role": "model", "parts": assistant_message.parts})
            
            # Build tool response messages for Gemini using proper SDK objects
            for tool_call, tool_result in zip(tool_calls, tool_results):
                # Convert tool result to JSON-serializable format using comprehensive function
                result_data = make_json_serializable(tool_result["result"])
                
                # Create function response using proper SDK structure
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
            
            # Log messages before calling Gemini (second call with tool results)
            logger.info("=" * 80)
            logger.info("CALLING GEMINI API (Second Call - After Tool Execution) - WebSocket")
            logger.info(f"Number of messages: {len(messages)}")
            for i, msg in enumerate(messages):
                msg_role = msg.get('role')
                logger.info(f"Message {i+1}: role={msg_role}")
                if msg_role == 'function':
                    parts = msg.get('parts', [])
                    if parts and hasattr(parts[0], 'function_response'):
                        func_name = parts[0].function_response.name
                        logger.info(f"  - Function response for: {func_name}")
            logger.info(f"Tool results being sent: {len(tool_results)} results")
            for tr in tool_results:
                logger.info(f"  - Tool: {tr['tool']}, Success: {tr['result'].get('success', False)}")
            logger.info("=" * 80)
            
            # Get final response from Gemini after processing tool results
            logger.info("Getting final response from Gemini after tool execution...")
            final_response = model.generate_content(
                messages,
                generation_config=genai.GenerationConfig(
                    temperature=0.2
                )
            )
            
            # Extract final response content
            final_assistant_content = ""
            if hasattr(final_response.candidates[0].content, 'parts'):
                for part in final_response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        final_assistant_content += part.text
            
            # Store final assistant message
            logger.debug("Storing final assistant message...")
            final_assistant_msg = Message(
                user_id=user.id,
                role="assistant",
                content=final_assistant_content
            )
            db.add(final_assistant_msg)
            db.commit()
            logger.debug(f"Final assistant message stored with ID: {final_assistant_msg.id}")
            
            assistant_content = final_assistant_content
            logger.info(f"Final response generated: {len(assistant_content)} characters")
        
        # Send final response
        # Make tool_results JSON serializable before sending via WebSocket
        serializable_tool_results = []
        if tool_calls and tool_results:
            for tool_result in tool_results:
                serializable_result = {
                    "tool": tool_result["tool"],
                    "result": make_json_serializable(tool_result["result"])
                }
                serializable_tool_results.append(serializable_result)
        
        await manager.send_personal_message({
            "type": "assistant_response",
            "content": assistant_content,
            "tool_calls": serializable_tool_results
        }, websocket)
        
        logger.info(f"Streaming message processing completed successfully. Response length: {len(assistant_content)} characters")
        
    except Exception as e:
        logger.error(f"Error processing streaming message: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error details: {str(e)}")
        await manager.send_personal_message({
            "type": "error",
            "content": "I apologize, but I encountered an error processing your request."
        }, websocket)

# Regular HTTP chat endpoint (for backward compatibility)
@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Chat with the AI agent"""
    logger.info(f"Chat request from user {user.id}: {request.message[:100]}...")
    
    try:
        logger.debug("Processing chat message with agent runtime...")
        result = agent_runtime.process_message(user, request.message, db)
        
        logger.info(f"Chat processing completed. Success: {result['success']}, Tool calls: {len(result.get('tool_calls', []))}")
        
        return ChatResponse(
            success=result["success"],
            response=result.get("response", ""),
            tool_calls=result.get("tool_calls"),
            error=result.get("error")
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error details: {str(e)}")
        return ChatResponse(
            success=False,
            response="I apologize, but I encountered an error processing your request.",
            error=str(e)
        )

# Instructions endpoints
@app.get("/instructions", response_model=List[InstructionResponse])
async def get_instructions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all instructions for user"""
    logger.info(f"Getting instructions for user {user.id}")
    
    try:
        instructions = db.query(Instruction).filter(Instruction.user_id == user.id).all()
        logger.info(f"Found {len(instructions)} instructions for user {user.id}")
        
        return [
            InstructionResponse(
                id=instruction.id,
                content=instruction.content,
                is_active=instruction.is_active,
                created_at=instruction.created_at.isoformat()
            )
            for instruction in instructions
        ]
    except Exception as e:
        logger.error(f"Error getting instructions: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to retrieve instructions")

@app.post("/instructions", response_model=InstructionResponse)
async def create_instruction(
    request: InstructionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new instruction"""
    logger.info(f"Creating instruction for user {user.id}: {request.content[:50]}...")
    
    try:
        instruction = Instruction(
            user_id=user.id,
            content=request.content,
            is_active=True
        )
        db.add(instruction)
        db.commit()
        db.refresh(instruction)
        
        logger.info(f"Created instruction {instruction.id} for user {user.id}")
        
        return InstructionResponse(
            id=instruction.id,
            content=instruction.content,
            is_active=instruction.is_active,
            created_at=instruction.created_at.isoformat()
        )
    except Exception as e:
        logger.error(f"Error creating instruction: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create instruction")

@app.patch("/instructions/{instruction_id}")
async def update_instruction(
    instruction_id: str,
    is_active: bool,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update instruction active status"""
    instruction = db.query(Instruction).filter(
        Instruction.id == instruction_id,
        Instruction.user_id == user.id
    ).first()
    
    if not instruction:
        raise HTTPException(status_code=404, detail="Instruction not found")
    
    instruction.is_active = is_active
    db.commit()
    
    return {"success": True}

# Tasks endpoints
@app.get("/tasks", response_model=List[TaskResponse])
async def get_tasks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all tasks for user"""
    tasks = db.query(Task).filter(Task.user_id == user.id).all()
    
    return [
        TaskResponse(
            id=task.id,
            title=task.title,
            status=task.status,
            data=task.data,
            created_at=task.created_at.isoformat(),
            updated_at=task.updated_at.isoformat()
        )
        for task in tasks
    ]

# Clear chat history endpoint
@app.delete("/chat/history")
async def clear_chat_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clear all chat history for the current user"""
    logger.info(f"Clearing chat history for user {user.id}")
    
    try:
        # Count messages before deletion
        message_count = db.query(Message).filter(Message.user_id == user.id).count()
        
        # Delete all messages for this user
        db.query(Message).filter(Message.user_id == user.id).delete()
        db.commit()
        
        logger.info(f"Successfully deleted {message_count} messages for user {user.id}")
        
        return {
            "success": True,
            "message": f"Successfully cleared {message_count} messages",
            "deleted_count": message_count
        }
    except Exception as e:
        logger.error(f"Error clearing chat history: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to clear chat history")

# Debug endpoints
@app.get("/debug/last-sync")
async def get_last_sync(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get last sync timestamps for debugging"""
    # This would be implemented with proper sync tracking
    # For now, return placeholder data
    return {
        "gmail": "2024-01-01T00:00:00Z",
        "calendar": "2024-01-01T00:00:00Z",
        "hubspot": "2024-01-01T00:00:00Z"
    }

# Admin endpoints for initial setup
@app.post("/admin/ingest-initial")
async def ingest_initial_data(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Trigger initial data ingestion for user (asynchronous)"""
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    
    # Initialize job tracking
    active_ingestions[job_id] = {
        "user_id": user.id,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "results": None,
                "error": None
    }
    
    # Start background ingestion
    thread = threading.Thread(target=run_background_ingestion, args=(user.id, job_id))
    thread.daemon = True
    thread.start()
    
    logger.info(f"Started background ingestion job {job_id} for user {user.id}")
    
    return {
        "success": True,
        "job_id": job_id,
        "status": "queued",
        "message": "Ingestion started in background. Use /admin/ingest-status/{job_id} to check progress."
    }

@app.get("/admin/ingest-status/{job_id}")
async def get_ingest_status(
    job_id: str,
    user: User = Depends(get_current_user)
):
    """Get status of ingestion job"""
    if job_id not in active_ingestions:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = active_ingestions[job_id]
    
    # Verify job belongs to user
    if job["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return job

# Webhook endpoints
@app.post("/webhooks/gmail")
async def gmail_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Gmail push notifications"""
    try:
        # Get headers
        channel_id = request.headers.get('X-Goog-Channel-ID')
        resource_id = request.headers.get('X-Goog-Resource-ID')
        resource_state = request.headers.get('X-Goog-Resource-State')
        message_number = request.headers.get('X-Goog-Message-Number', '0')
        
        logger.info(f"Gmail webhook received - Channel: {channel_id}, State: {resource_state}")
        
        # Handle sync verification
        if resource_state == 'sync':
            logger.info("Gmail sync verification received")
            return {"status": "ok"}
        
        # Process notification
        success = webhook_handler.handle_gmail_notification(
            channel_id=channel_id,
            resource_id=resource_id,
            message_number=message_number,
            db=db
        )
        
        return {"status": "ok" if success else "error"}
        
    except Exception as e:
        logger.error(f"Error handling Gmail webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/webhooks/calendar")
async def calendar_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Google Calendar push notifications"""
    try:
        # Get headers
        channel_id = request.headers.get('X-Goog-Channel-ID')
        resource_id = request.headers.get('X-Goog-Resource-ID')
        resource_state = request.headers.get('X-Goog-Resource-State')
        
        logger.info(f"Calendar webhook received - Channel: {channel_id}, State: {resource_state}")
        
        # Process notification
        success = webhook_handler.handle_calendar_notification(
            channel_id=channel_id,
            resource_id=resource_id,
            resource_state=resource_state,
            db=db
        )
        
        return {"status": "ok" if success else "error"}
        
    except Exception as e:
        logger.error(f"Error handling Calendar webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/webhooks/hubspot")
async def hubspot_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle HubSpot webhooks
    
    HubSpot Target URL: learn-jump.onrender.com/webhooks/hubspot
    
    Receives webhooks for:
    - contact.creation
    - contact.propertyChange
    - contact.deletion
    - deal.creation, deal.propertyChange, deal.deletion
    - And other HubSpot object events
    """
    try:
        # Parse webhook payload
        payload = await request.json()
        
        logger.info(f"=== HubSpot Webhook Received ===")
        logger.info(f"Payload: {json.dumps(payload, indent=2)}")
        
        # HubSpot sends an array of events
        events_processed = 0
        if isinstance(payload, list):
            for event in payload:
                subscription_type = event.get('subscriptionType', '')
                object_id = event.get('objectId', '')
                event_type = event.get('changeSource', '')
                
                logger.info(f"Processing HubSpot event: {subscription_type} - {event_type} - Object ID: {object_id}")
                
                success = webhook_handler.handle_hubspot_webhook(
                    subscription_type=subscription_type,
                    object_id=object_id,
                    event_type=event_type,
                    payload=event,
                    db=db
                )
                
                if success:
                    events_processed += 1
        else:
            # Single event
            subscription_type = payload.get('subscriptionType', '')
            object_id = payload.get('objectId', '')
            event_type = payload.get('changeSource', '')
            
            logger.info(f"Processing single HubSpot event: {subscription_type} - {event_type} - Object ID: {object_id}")
            
            success = webhook_handler.handle_hubspot_webhook(
                subscription_type=subscription_type,
                object_id=object_id,
                event_type=event_type,
                payload=payload,
                db=db
            )
            
            if success:
                events_processed = 1
        
        logger.info(f"HubSpot webhook processing complete: {events_processed} events processed")
        return {"status": "ok", "events_processed": events_processed}
        
    except Exception as e:
        logger.error(f"Error handling HubSpot webhook: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}

# Webhook setup endpoints
@app.post("/admin/webhooks/setup")
async def setup_webhooks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Set up push notifications for Gmail and Calendar"""
    try:
        from googleapiclient.discovery import build
        import uuid as uuid_lib
        from datetime import datetime, timedelta
        
        credentials = google_service.get_credentials(user, db)
        if not credentials:
            return {"success": False, "error": "No valid credentials"}
        
        results = {
            "gmail": {"success": False},
            "calendar": {"success": False}
        }
        
        # Set up Gmail push notification
        try:
            gmail_service = build('gmail', 'v1', credentials=credentials)
            
            channel_id = str(uuid_lib.uuid4())
            
            # Note: You need to set up a Cloud Pub/Sub topic first
            # For now, we'll use the webhook endpoint
            watch_request = {
                'labelIds': ['INBOX'],
                'topicName': f'projects/{settings.GOOGLE_PROJECT_ID}/topics/gmail-push'
            }
            
            # This requires Cloud Pub/Sub setup, so we'll skip for now
            logger.info("Gmail webhook setup requires Cloud Pub/Sub configuration")
            results["gmail"]["success"] = False
            results["gmail"]["message"] = "Requires Cloud Pub/Sub setup"
            
        except Exception as e:
            logger.error(f"Error setting up Gmail webhook: {e}")
            results["gmail"]["error"] = str(e)
        
        # Set up Calendar push notification
        try:
            calendar_service = build('calendar', 'v3', credentials=credentials)
            
            channel_id = str(uuid_lib.uuid4())
            expiration = int((datetime.utcnow() + timedelta(days=7)).timestamp() * 1000)
            
            watch_request = {
                'id': channel_id,
                'type': 'web_hook',
                'address': f'{settings.APP_URL}/webhooks/calendar',
                'expiration': expiration
            }
            
            response = calendar_service.events().watch(
                calendarId='primary',
                body=watch_request
            ).execute()
            
            # Save subscription
            subscription = WebhookSubscription(
                user_id=user.id,
                provider='calendar',
                resource_id=response.get('resourceId'),
                channel_id=channel_id,
                expiration=datetime.fromtimestamp(expiration / 1000),
                is_active=True
            )
            db.add(subscription)
            db.commit()
            
            results["calendar"]["success"] = True
            results["calendar"]["channel_id"] = channel_id
            
        except Exception as e:
            logger.error(f"Error setting up Calendar webhook: {e}")
            results["calendar"]["error"] = str(e)
        
        return results
        
    except Exception as e:
        logger.error(f"Error setting up webhooks: {e}")
        return {"success": False, "error": str(e)}

@app.get("/admin/webhooks/status")
async def get_webhook_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get status of active webhooks"""
    subscriptions = db.query(WebhookSubscription).filter(
        WebhookSubscription.user_id == user.id,
        WebhookSubscription.is_active == True
    ).all()
    
    return {
        "subscriptions": [
            {
                "provider": sub.provider,
                "channel_id": sub.channel_id,
                "expiration": sub.expiration.isoformat() if sub.expiration else None,
                "created_at": sub.created_at.isoformat() if sub.created_at else None
            }
            for sub in subscriptions
        ]
    }

# Debug endpoints for proactive agent
@app.get("/debug/webhook-events")
async def debug_webhook_events(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 10
):
    """Debug: Get recent webhook events"""
    events = db.query(WebhookEvent).filter(
        WebhookEvent.user_id == user.id
    ).order_by(WebhookEvent.created_at.desc()).limit(limit).all()
    
    return {
        "events": [
            {
                "id": event.id,
                "provider": event.provider,
                "event_type": event.event_type,
                "resource_id": event.resource_id,
                "processed": event.processed,
                "processed_at": event.processed_at.isoformat() if event.processed_at else None,
                "error": event.error,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "payload": event.payload
            }
            for event in events
        ]
    }

@app.get("/debug/instructions")
async def debug_instructions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug: Get ongoing instructions"""
    instructions = db.query(Instruction).filter(
        Instruction.user_id == user.id
    ).order_by(Instruction.created_at.desc()).all()
    
    return {
        "instructions": [
            {
                "id": inst.id,
                "content": inst.content,
                "is_active": inst.is_active,
                "created_at": inst.created_at.isoformat() if inst.created_at else None
            }
            for inst in instructions
        ]
    }

@app.get("/debug/tasks")
async def debug_tasks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: Optional[str] = None
):
    """Debug: Get tasks"""
    query = db.query(Task).filter(Task.user_id == user.id)
    if status:
        query = query.filter(Task.status == status)
    
    tasks = query.order_by(Task.created_at.desc()).limit(20).all()
    
    return {
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "data": task.data,
                "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
                "created_at": task.created_at.isoformat() if task.created_at else None
            }
            for task in tasks
        ]
    }

@app.post("/debug/test-proactive")
async def test_proactive_agent(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Debug: Test proactive agent with a mock event"""
    from agent.proactive import proactive_agent
    
    # Create a test webhook event
    test_event = WebhookEvent(
        user_id=user.id,
        provider='gmail',
        event_type='new_email',
        resource_id='test-email-123',
        payload={
            'from': 'test@example.com',
            'subject': 'Test Email for Proactive Agent',
            'body': 'This is a test email to trigger proactive actions'
        }
    )
    db.add(test_event)
    db.commit()
    
    # Process the event
    try:
        result = await proactive_agent.process_webhook_event(test_event, db)
        
        # Mark as processed
        test_event.processed = True
        test_event.processed_at = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "test_event_id": test_event.id,
            "result": result
        }
    except Exception as e:
        logger.error(f"Error testing proactive agent: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/debug/worker-status")
async def debug_worker_status():
    """Debug: Check proactive worker status"""
    global proactive_worker
    
    return {
        "worker_initialized": proactive_worker is not None,
        "worker_running": proactive_worker.running if proactive_worker else False,
        "worker_thread_alive": any(
            thread.name == "ProactiveWorker" and thread.is_alive() 
            for thread in threading.enumerate()
        )
    }

# Serve static assets manually
@app.get("/assets/{filename}")
async def serve_asset(filename: str):
    """Serve static assets"""
    asset_path = os.path.join(static_dir, "assets", filename)
    if os.path.exists(asset_path):
        return FileResponse(asset_path)
    else:
        raise HTTPException(status_code=404, detail="Asset not found")

# Catch-all route for SPA routing (must be last)
@app.get("/{path:path}")
async def serve_frontend_spa(path: str):
    """Serve frontend for SPA routing - only for non-API paths"""
    # Skip if it's an API route or already handled route
    if (path.startswith(("api/", "auth/", "me", "chat", "instructions", "tasks", "debug", "admin", "health", "assets/", "static/")) or 
        path in ("", "app")):
        raise HTTPException(status_code=404, detail="Not found")
    
    # Serve index.html for SPA routes
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    else:
        raise HTTPException(status_code=404, detail="Frontend not built")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
