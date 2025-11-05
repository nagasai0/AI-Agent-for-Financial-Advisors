from sqlalchemy.orm import Session
from models_temp import User, Doc, Chunk
from services.google import GoogleService
from services.hubspot import HubSpotService
from config import settings
import google.generativeai as genai
import numpy as np
import tiktoken
from typing import List, Dict
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Initialize Google AI
genai.configure(api_key=settings.GOOGLE_API_KEY)

class RAGIngester:
    def __init__(self):
        self.google_service = GoogleService()
        self.hubspot_service = HubSpotService()
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.chunk_size = 1000  # tokens
        self.chunk_overlap = 200  # tokens
    
    def embed_text(self, text: str) -> str:
        """Generate embedding for text using Google AI and return as JSON string"""
        try:
            result = genai.embed_content(model="models/text-embedding-004", content=text)
            embedding_array = result['embedding']
            # Convert to JSON string for storage in embedding_text field
            import json
            return json.dumps(embedding_array)
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return json.dumps([0.0] * 768)  # Return zero vector as JSON string on error
    
    def chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks"""
        tokens = self.encoding.encode(text)
        chunks = []
        
        for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
            chunk_tokens = tokens[i:i + self.chunk_size]
            chunk_text = self.encoding.decode(chunk_tokens)
            chunks.append(chunk_text)
        
        return chunks
    
    def store_doc_chunks_batch(self, user: User, documents: List[Dict], db: Session):
        """Store multiple documents and their chunks with embeddings in batch"""
        logger.info(f"Storing {len(documents)} documents in batch for user {user.id}")
        
        processed_count = 0
        error_count = 0
        
        for doc_data in documents:
            try:
                self.store_doc_chunks(
                    user=user,
                    source=doc_data['source'],
                    source_id=doc_data['source_id'],
                    content=doc_data['content'],
                    subject=doc_data.get('subject'),
                    contact_email=doc_data.get('contact_email'),
                    db=db
                )
                processed_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"Error storing document {doc_data.get('source_id', 'unknown')}: {e}")
                continue
        
        logger.info(f"Batch storage completed: {processed_count} documents processed, {error_count} errors")
        return {"processed": processed_count, "errors": error_count}
    
    def store_doc_chunks(self, user: User, source: str, source_id: str, content: str, 
                        subject: str = None, contact_email: str = None, db: Session = None):
        """Store document and its chunks with embeddings"""
        # Create or update doc
        doc = db.query(Doc).filter(
            Doc.user_id == user.id,
            Doc.source == source,
            Doc.source_id == source_id
        ).first()
        
        if doc:
            # Update existing doc
            doc.snippet = content[:500] + "..." if len(content) > 500 else content
            doc.updated_at = datetime.utcnow()
        else:
            # Create new doc
            doc = Doc(
                user_id=user.id,
                source=source,
                source_id=source_id,
                subject=subject,
                contact_email=contact_email,
                snippet=content[:500] + "..." if len(content) > 500 else content
            )
            db.add(doc)
            db.flush()  # Get the ID
        
        # Delete existing chunks
        db.query(Chunk).filter(Chunk.doc_id == doc.id).delete()
        
        # Create new chunks
        chunks = self.chunk_text(content)
        for idx, chunk_text in enumerate(chunks):
            embedding_text = self.embed_text(chunk_text)

            chunk = Chunk(
                doc_id=doc.id,
                user_id=user.id,
                content=chunk_text,
                embedding_text=embedding_text,
                idx=idx
            )
            db.add(chunk)
        
        db.commit()
        logger.info(f"Stored {len(chunks)} chunks for {source} document {source_id}")
    
    def ingest_gmail_initial(self, user: User, db: Session):
        """Initial Gmail ingestion - get last 30 days with improved error handling"""
        logger.info(f"Starting initial Gmail ingestion for user {user.id}")
        
        # Get messages from last 30 days
        since_date = datetime.utcnow() - timedelta(days=30)
        logger.info(f"Fetching Gmail messages since: {since_date}")
        
        try:
            # Use batch processing for better performance
            messages = self.google_service.gmail_list_since_batch(user, since_date, db, batch_size=10)
            logger.info(f"Retrieved {len(messages)} Gmail messages from API using batch processing")
            
            if not messages:
                logger.warning("No Gmail messages retrieved - this could indicate API issues or empty inbox")
                return {"status": "no_messages", "count": 0, "error": None}
            
            processed_count = 0
            error_count = 0
            skipped_count = 0
            
            for i, msg in enumerate(messages):
                logger.debug(f"Processing Gmail message {i+1}/{len(messages)}: {msg.get('subject', 'No Subject')[:50]}...")
                
                try:
                    # Validate message data
                    if not msg.get('id') or not msg.get('subject'):
                        logger.warning(f"Skipping message {i+1} - missing required fields")
                        skipped_count += 1
                        continue
                    
                    # Combine subject and body for content
                    content = f"Subject: {msg['subject']}\n\n{msg.get('body', '')}"
                    
                    # Skip if content is too short (likely spam or empty)
                    if len(content.strip()) < 50:
                        logger.debug(f"Skipping message {msg['id']} - content too short")
                        skipped_count += 1
                        continue
                    
                    self.store_doc_chunks(
                        user=user,
                        source='gmail',
                        source_id=msg['id'],
                        content=content,
                        subject=msg['subject'],
                        contact_email=msg.get('from', ''),
                        db=db
                    )
                    processed_count += 1
                    logger.debug(f"Successfully stored Gmail message {msg['id']}")
                    
                except Exception as msg_error:
                    error_count += 1
                    logger.error(f"Error processing Gmail message {msg.get('id', 'unknown')}: {msg_error}")
                    # Continue processing other messages instead of failing completely
                    continue
            
            logger.info(f"Completed initial Gmail ingestion: {processed_count} messages processed, {error_count} errors, {skipped_count} skipped")
            
            return {
                "status": "completed",
                "processed": processed_count,
                "errors": error_count,
                "skipped": skipped_count,
                "total": len(messages)
            }
            
        except Exception as e:
            logger.error(f"Failed to retrieve Gmail messages: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            raise
    
    def ingest_hubspot_initial(self, user: User, db: Session):
        """Initial HubSpot ingestion with improved error handling"""
        logger.info(f"Starting initial HubSpot ingestion for user {user.id}")
        
        results = {
            "contacts": {"processed": 0, "errors": 0, "skipped": 0},
            "notes": {"processed": 0, "errors": 0, "skipped": 0}
        }
        
        try:
            logger.info("Fetching HubSpot contacts...")
            # Get recent contacts with error handling
            try:
                contacts = self.hubspot_service.hs_get_recent_contacts(user, limit=50, db=db)
                logger.info(f"Retrieved {len(contacts)} HubSpot contacts")
            except Exception as e:
                logger.error(f"Failed to fetch HubSpot contacts: {e}")
                contacts = []
                results["contacts"]["errors"] = 1
            
            for i, contact in enumerate(contacts):
                logger.debug(f"Processing HubSpot contact {i+1}/{len(contacts)}: {contact.get('name', 'Unknown')}")
                
                try:
                    # Validate contact data
                    if not contact.get('id') or not contact.get('name'):
                        logger.warning(f"Skipping contact {i+1} - missing required fields")
                        results["contacts"]["skipped"] += 1
                        continue
                    
                    # Check if we already have this contact
                    existing = db.query(Doc).filter(
                        Doc.user_id == user.id,
                        Doc.source == 'hubspot_contact',
                        Doc.source_id == contact['id']
                    ).first()
                    
                    if not existing:
                        content = f"Contact: {contact['name']}\nEmail: {contact.get('email', 'N/A')}\nCreated: {contact.get('created_at', 'N/A')}"
                        
                        self.store_doc_chunks(
                            user=user,
                            source='hubspot_contact',
                            source_id=contact['id'],
                            content=content,
                            contact_email=contact.get('email', ''),
                            db=db
                        )
                        results["contacts"]["processed"] += 1
                        logger.debug(f"Successfully stored HubSpot contact {contact['id']}")
                    else:
                        logger.debug(f"HubSpot contact {contact['id']} already exists, skipping")
                        results["contacts"]["skipped"] += 1
                        
                except Exception as contact_error:
                    results["contacts"]["errors"] += 1
                    logger.error(f"Error processing HubSpot contact {contact.get('id', 'unknown')}: {contact_error}")
                    continue
            
            logger.info("Fetching HubSpot notes...")
            # Get recent notes with error handling
            try:
                notes = self.hubspot_service.hs_get_recent_notes(user, limit=50, db=db)
                logger.info(f"Retrieved {len(notes)} HubSpot notes")
            except Exception as e:
                logger.error(f"Failed to fetch HubSpot notes: {e}")
                notes = []
                results["notes"]["errors"] = 1
            
            for i, note in enumerate(notes):
                logger.debug(f"Processing HubSpot note {i+1}/{len(notes)}: {note.get('body', 'No content')[:50]}...")
                
                try:
                    # Validate note data
                    if not note.get('id') or not note.get('body'):
                        logger.warning(f"Skipping note {i+1} - missing required fields")
                        results["notes"]["skipped"] += 1
                        continue
                    
                    # Check if we already have this note
                    existing = db.query(Doc).filter(
                        Doc.user_id == user.id,
                        Doc.source == 'hubspot_note',
                        Doc.source_id == note['id']
                    ).first()
                    
                    if not existing:
                        self.store_doc_chunks(
                            user=user,
                            source='hubspot_note',
                            source_id=note['id'],
                            content=note['body'],
                            db=db
                        )
                        results["notes"]["processed"] += 1
                        logger.debug(f"Successfully stored HubSpot note {note['id']}")
                    else:
                        logger.debug(f"HubSpot note {note['id']} already exists, skipping")
                        results["notes"]["skipped"] += 1
                        
                except Exception as note_error:
                    results["notes"]["errors"] += 1
                    logger.error(f"Error processing HubSpot note {note.get('id', 'unknown')}: {note_error}")
                    continue
            
            total_processed = results["contacts"]["processed"] + results["notes"]["processed"]
            total_errors = results["contacts"]["errors"] + results["notes"]["errors"]
            
            logger.info(f"Completed initial HubSpot ingestion: {total_processed} items processed, {total_errors} errors")
            logger.info(f"Contacts: {results['contacts']['processed']} processed, {results['contacts']['errors']} errors, {results['contacts']['skipped']} skipped")
            logger.info(f"Notes: {results['notes']['processed']} processed, {results['notes']['errors']} errors, {results['notes']['skipped']} skipped")
            
            return {
                "status": "completed",
                "total_processed": total_processed,
                "total_errors": total_errors,
                "details": results
            }
            
        except Exception as e:
            logger.error(f"Failed to complete HubSpot ingestion: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            raise
    
    def ingest_incremental_gmail(self, user: User, last_sync: datetime, db: Session):
        """Incremental Gmail ingestion"""
        logger.info(f"Starting incremental Gmail ingestion for user {user.id}")
        
        messages = self.google_service.gmail_list_since(user, last_sync, db)
        
        for msg in messages:
            content = f"Subject: {msg['subject']}\n\n{msg['body']}"
            
            self.store_doc_chunks(
                user=user,
                source='gmail',
                source_id=msg['id'],
                content=content,
                subject=msg['subject'],
                contact_email=msg['from'],
                db=db
            )
        
        logger.info(f"Completed incremental Gmail ingestion: {len(messages)} new messages")
        return len(messages)
    
    def ingest_incremental_hubspot(self, user: User, last_sync: datetime, db: Session):
        """Incremental HubSpot ingestion"""
        logger.info(f"Starting incremental HubSpot ingestion for user {user.id}")
        
        # For simplicity, we'll get recent contacts and notes
        # In production, you'd want to use HubSpot's webhooks or timestamp filtering
        contacts = self.hubspot_service.hs_get_recent_contacts(user, limit=20, db=db)
        notes = self.hubspot_service.hs_get_recent_notes(user, limit=20, db=db)
        
        new_contacts = 0
        new_notes = 0
        
        for contact in contacts:
            # Check if we already have this contact
            existing = db.query(Doc).filter(
                Doc.user_id == user.id,
                Doc.source == 'hubspot_contact',
                Doc.source_id == contact['id']
            ).first()
            
            if not existing:
                content = f"Contact: {contact['name']}\nEmail: {contact['email']}\nCreated: {contact['created_at']}"
                
                self.store_doc_chunks(
                    user=user,
                    source='hubspot_contact',
                    source_id=contact['id'],
                    content=content,
                    contact_email=contact['email'],
                    db=db
                )
                new_contacts += 1
        
        for note in notes:
            # Check if we already have this note
            existing = db.query(Doc).filter(
                Doc.user_id == user.id,
                Doc.source == 'hubspot_note',
                Doc.source_id == note['id']
            ).first()
            
            if not existing:
                self.store_doc_chunks(
                    user=user,
                    source='hubspot_note',
                    source_id=note['id'],
                    content=note['body'],
                    db=db
                )
                new_notes += 1
        
        logger.info(f"Completed incremental HubSpot ingestion: {new_contacts} new contacts, {new_notes} new notes")
        return new_contacts + new_notes
