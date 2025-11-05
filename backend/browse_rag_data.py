#!/usr/bin/env python3
"""
Script to browse RAG data directly from the database
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database_temp import SessionLocal
from models_temp import User, Doc, Chunk
from sqlalchemy.orm import joinedload
import json

def browse_rag_data():
    """Browse RAG data in the database"""
    db = SessionLocal()
    
    try:
        print("=== RAG Data Browser ===\n")
        
        # Get all users
        users = db.query(User).all()
        print(f"Found {len(users)} users:")
        for user in users:
            print(f"  - {user.name} ({user.email}) - ID: {user.id}")
        
        if not users:
            print("No users found!")
            return
        
        # Let user choose which user to browse
        if len(users) == 1:
            selected_user = users[0]
        else:
            print("\nSelect a user to browse:")
            for i, user in enumerate(users):
                print(f"{i+1}. {user.name} ({user.email})")
            
            try:
                choice = int(input("Enter choice (number): ")) - 1
                selected_user = users[choice]
            except (ValueError, IndexError):
                print("Invalid choice, using first user")
                selected_user = users[0]
        
        print(f"\n=== Browsing data for {selected_user.name} ===\n")
        
        # Get document counts by source
        docs_by_source = db.query(Doc.source, db.func.count(Doc.id)).filter(
            Doc.user_id == selected_user.id
        ).group_by(Doc.source).all()
        
        print("Documents by source:")
        for source, count in docs_by_source:
            print(f"  - {source}: {count} documents")
        
        # Get total chunks
        total_chunks = db.query(Chunk).filter(Chunk.user_id == selected_user.id).count()
        print(f"Total chunks: {total_chunks}\n")
        
        # Show recent documents
        print("Recent documents:")
        recent_docs = db.query(Doc).filter(
            Doc.user_id == selected_user.id
        ).order_by(Doc.created_at.desc()).limit(10).all()
        
        for i, doc in enumerate(recent_docs, 1):
            print(f"{i}. [{doc.source}] {doc.subject or 'No subject'}")
            print(f"   Source ID: {doc.source_id}")
            print(f"   Contact: {doc.contact_email or 'N/A'}")
            print(f"   Created: {doc.created_at}")
            print(f"   Snippet: {doc.snippet[:100] if doc.snippet else 'No snippet'}...")
            print()
        
        # Interactive browsing
        while True:
            print("\nOptions:")
            print("1. View document details")
            print("2. Search documents")
            print("3. View chunks for a document")
            print("4. View embedding info")
            print("5. Exit")
            
            choice = input("Enter choice (1-5): ").strip()
            
            if choice == "1":
                view_document_details(db, selected_user.id)
            elif choice == "2":
                search_documents(db, selected_user.id)
            elif choice == "3":
                view_chunks(db, selected_user.id)
            elif choice == "4":
                view_embedding_info(db, selected_user.id)
            elif choice == "5":
                break
            else:
                print("Invalid choice")
    
    finally:
        db.close()

def view_document_details(db, user_id):
    """View details of a specific document"""
    doc_id = input("Enter document ID: ").strip()
    
    doc = db.query(Doc).filter(
        Doc.id == doc_id,
        Doc.user_id == user_id
    ).first()
    
    if not doc:
        print("Document not found!")
        return
    
    print(f"\n=== Document Details ===")
    print(f"ID: {doc.id}")
    print(f"Source: {doc.source}")
    print(f"Source ID: {doc.source_id}")
    print(f"Subject: {doc.subject}")
    print(f"Contact Email: {doc.contact_email}")
    print(f"Created: {doc.created_at}")
    print(f"Updated: {doc.updated_at}")
    print(f"Snippet: {doc.snippet}")
    
    # Show chunks
    chunks = db.query(Chunk).filter(Chunk.doc_id == doc.id).order_by(Chunk.idx).all()
    print(f"\nChunks ({len(chunks)}):")
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1}: {chunk.content[:100]}...")

def search_documents(db, user_id):
    """Search documents by content"""
    query = input("Enter search query: ").strip()
    
    docs = db.query(Doc).filter(
        Doc.user_id == user_id,
        (Doc.snippet.ilike(f"%{query}%")) |
        (Doc.subject.ilike(f"%{query}%")) |
        (Doc.contact_email.ilike(f"%{query}%"))
    ).order_by(Doc.created_at.desc()).limit(10).all()
    
    print(f"\nFound {len(docs)} documents matching '{query}':")
    for i, doc in enumerate(docs, 1):
        print(f"{i}. [{doc.source}] {doc.subject or 'No subject'}")
        print(f"   ID: {doc.id}")
        print(f"   Contact: {doc.contact_email or 'N/A'}")
        print(f"   Created: {doc.created_at}")
        print()

def view_chunks(db, user_id):
    """View chunks for a document"""
    doc_id = input("Enter document ID: ").strip()
    
    chunks = db.query(Chunk).filter(
        Chunk.doc_id == doc_id,
        Chunk.user_id == user_id
    ).order_by(Chunk.idx).all()
    
    if not chunks:
        print("No chunks found for this document!")
        return
    
    print(f"\n=== Chunks for Document {doc_id} ===")
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i+1} (Index: {chunk.idx}):")
        print(f"ID: {chunk.id}")
        print(f"Content: {chunk.content}")
        print(f"Created: {chunk.created_at}")
        
        if chunk.embedding_text:
            try:
                embedding = json.loads(chunk.embedding_text)
                print(f"Embedding: {len(embedding)} dimensions")
                print(f"First 5 values: {embedding[:5]}")
            except:
                print("Embedding: Invalid JSON")

def view_embedding_info(db, user_id):
    """View embedding statistics"""
    chunks_with_embeddings = db.query(Chunk).filter(
        Chunk.user_id == user_id,
        Chunk.embedding_text.isnot(None)
    ).count()
    
    total_chunks = db.query(Chunk).filter(Chunk.user_id == user_id).count()
    
    print(f"\n=== Embedding Statistics ===")
    print(f"Total chunks: {total_chunks}")
    print(f"Chunks with embeddings: {chunks_with_embeddings}")
    print(f"Coverage: {(chunks_with_embeddings/total_chunks*100):.1f}%" if total_chunks > 0 else "N/A")
    
    # Show sample embedding
    sample_chunk = db.query(Chunk).filter(
        Chunk.user_id == user_id,
        Chunk.embedding_text.isnot(None)
    ).first()
    
    if sample_chunk:
        try:
            embedding = json.loads(sample_chunk.embedding_text)
            print(f"\nSample embedding:")
            print(f"Dimensions: {len(embedding)}")
            print(f"First 10 values: {embedding[:10]}")
            print(f"Last 10 values: {embedding[-10:]}")
        except Exception as e:
            print(f"Error parsing embedding: {e}")

if __name__ == "__main__":
    browse_rag_data()
