from sqlalchemy.orm import Session
from models_temp import User, Chunk, Doc
from config import settings
import google.generativeai as genai
import numpy as np
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

# Initialize Google AI
genai.configure(api_key=settings.GOOGLE_API_KEY)

class RAGQuery:
    def __init__(self):
        pass
    
    def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for query"""
        logger.debug(f"Generating embedding for query: {query[:50]}...")
        
        try:
            result = genai.embed_content(model="models/text-embedding-004", content=query)
            embedding = np.array(result['embedding'])
            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
            return embedding
        except Exception as e:
            logger.error(f"Error generating query embedding: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            return np.zeros(768)
    
    def similar_chunks(self, user_id: str, query: str, k: int = 12, db: Session = None) -> List[Dict]:
        """Find similar chunks using keyword matching and recency"""
        logger.debug(f"Finding similar chunks for user {user_id}, query: {query[:50]}..., k={k}")
        
        try:
            # Extract keywords from query for better matching
            # Keep important short words like "kid", "son", "mom", etc.
            query_lower = query.lower()
            stop_words = {'who', 'what', 'when', 'where', 'why', 'how', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'is', 'was', 'are', 'were', 'been', 'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'their', 'them', 'they', 'that', 'this', 'these', 'those'}
            keywords = [word.strip() for word in query_lower.split() if len(word.strip()) >= 3 and word.strip() not in stop_words]
            
            logger.debug(f"Extracted keywords: {keywords}")
            
            # Start with recent chunks
            query_obj = db.query(Chunk, Doc).join(Doc).filter(Chunk.user_id == user_id)
            
            # If we have keywords, try to match them
            if keywords:
                logger.debug(f"Searching with {len(keywords)} keywords")
                # Build OR conditions for keyword matching
                from sqlalchemy import or_
                conditions = []
                for keyword in keywords[:8]:  # Increased to 8 keywords for better matching
                    conditions.append(Chunk.content.ilike(f"%{keyword}%"))
                    conditions.append(Doc.subject.ilike(f"%{keyword}%"))
                    conditions.append(Doc.snippet.ilike(f"%{keyword}%"))
                
                if conditions:
                    query_obj = query_obj.filter(or_(*conditions))
            
            # Order by created date (most recent first) and limit
            chunks = query_obj.order_by(Doc.created_at.desc()).limit(k * 2).all()
            logger.debug(f"Found {len(chunks)} chunks with keyword matching")
            
            # If we didn't get enough results with keywords, try partial phrase matching
            if len(chunks) < k and keywords:
                logger.debug(f"Not enough results ({len(chunks)}), trying phrase matching")
                # Try to find chunks with multiple keywords present
                phrase_chunks = db.query(Chunk, Doc).join(Doc).filter(
                    Chunk.user_id == user_id
                ).order_by(Doc.created_at.desc()).limit(50).all()
                
                # Score chunks by how many keywords they contain
                scored_chunks = []
                seen_ids = {chunk.id for chunk, _ in chunks}
                for chunk, doc in phrase_chunks:
                    if chunk.id in seen_ids:
                        continue
                    score = sum(1 for keyword in keywords if keyword in chunk.content.lower() or (doc.subject and keyword in doc.subject.lower()))
                    if score > 0:
                        scored_chunks.append((score, chunk, doc))
                
                # Add highest scoring chunks
                scored_chunks.sort(reverse=True, key=lambda x: x[0])
                for score, chunk, doc in scored_chunks:
                    if len(chunks) >= k:
                        break
                    chunks.append((chunk, doc))
                
                logger.debug(f"Added {len(scored_chunks)} phrase-matched chunks")
            
            # If still not enough results, get some recent chunks
            if len(chunks) < k:
                logger.debug(f"Still not enough results ({len(chunks)}), getting recent chunks")
                recent_chunks = db.query(Chunk, Doc).join(Doc).filter(
                    Chunk.user_id == user_id
                ).order_by(Doc.created_at.desc()).limit(k).all()
                
                # Merge results, avoiding duplicates
                seen_ids = {chunk.id for chunk, _ in chunks}
                for chunk, doc in recent_chunks:
                    if chunk.id not in seen_ids:
                        chunks.append((chunk, doc))
                        if len(chunks) >= k:
                            break
                
                logger.debug(f"Added recent chunks, total now: {len(chunks)}")

            results = []
            for chunk, doc in chunks[:k]:
                results.append({
                    'chunk_id': chunk.id,
                    'content': chunk.content,
                    'source': doc.source,
                    'source_id': doc.source_id,
                    'subject': doc.subject,
                    'contact_email': doc.contact_email,
                    'snippet': doc.snippet,
                    'created_at': doc.created_at.isoformat() if doc.created_at else None
                })

            logger.debug(f"Returning {len(results)} similar chunks")
            return results

        except Exception as e:
            logger.error(f"Error finding similar chunks: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            return []
    
    def build_context(self, user_id: str, query: str, k: int = 12, db: Session = None) -> str:
        """Build context string from similar chunks"""
        logger.debug(f"Building context for user {user_id}, query: {query[:50]}..., k={k}")
        
        chunks = self.similar_chunks(user_id, query, k, db)
        
        if not chunks:
            logger.debug("No chunks found, returning 'No relevant context found'")
            return "No relevant context found."
        
        logger.debug(f"Building context from {len(chunks)} chunks")
        
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            source_info = f"[{chunk['source']}]"
            if chunk['subject']:
                source_info += f" Subject: {chunk['subject']}"
            if chunk['contact_email']:
                source_info += f" From: {chunk['contact_email']}"
            if chunk['created_at']:
                source_info += f" Date: {chunk['created_at'][:10]}"
            
            context_parts.append(
                f"--- Context {i} ({source_info}) ---\n"
                f"{chunk['content']}\n"
            )
        
        context = "\n".join(context_parts)
        logger.debug(f"Built context with {len(context)} characters")
        return context
    
    def search_documents(self, user_id: str, query: str, source: str = None, limit: int = 10, db: Session = None) -> List[Dict]:
        """Search documents by content"""
        logger.debug(f"Searching documents for user {user_id}, query: {query[:50]}..., source: {source}, limit: {limit}")
        
        try:
            query_obj = db.query(Doc).filter(Doc.user_id == user_id)
            
            if source:
                logger.debug(f"Filtering by source: {source}")
                query_obj = query_obj.filter(Doc.source == source)
            
            # Simple text search in snippet and subject
            if query:
                logger.debug(f"Adding text search filters for: {query}")
                query_obj = query_obj.filter(
                    (Doc.snippet.ilike(f"%{query}%")) |
                    (Doc.subject.ilike(f"%{query}%")) |
                    (Doc.contact_email.ilike(f"%{query}%"))
                )
            
            docs = query_obj.order_by(Doc.created_at.desc()).limit(limit).all()
            logger.debug(f"Found {len(docs)} documents matching search criteria")
            
            results = []
            for doc in docs:
                results.append({
                    'id': doc.id,
                    'source': doc.source,
                    'source_id': doc.source_id,
                    'subject': doc.subject,
                    'contact_email': doc.contact_email,
                    'snippet': doc.snippet,
                    'created_at': doc.created_at.isoformat() if doc.created_at else None
                })
            
            logger.debug(f"Returning {len(results)} search results")
            return results
            
        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            return []
