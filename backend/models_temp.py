from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
# from pgvector.sqlalchemy import Vector  # Commented out for testing without pgvector
import uuid

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    google_email = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    instructions = relationship("Instruction", back_populates="user", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")
    docs = relationship("Doc", back_populates="user", cascade="all, delete-orphan")
    webhook_subscriptions = relationship("WebhookSubscription", back_populates="user", cascade="all, delete-orphan")
    sync_states = relationship("SyncState", back_populates="user", cascade="all, delete-orphan")

class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # 'google' or 'hubspot'
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    scope = Column(Text, nullable=True)
    expiry = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="accounts")
    
    # Indexes
    __table_args__ = (
        Index('idx_account_user_provider', 'user_id', 'provider', unique=True),
    )

class Instruction(Base):
    __tablename__ = "instructions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="instructions")

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending, waiting, done, failed
    data = Column(JSON, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="tasks")
    messages = relationship("Message", back_populates="task")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)  # user, assistant, tool, system
    content = Column(Text, nullable=False)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="messages")
    task = relationship("Task", back_populates="messages")

class Doc(Base):
    __tablename__ = "docs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    source = Column(String, nullable=False)  # gmail, hubspot_contact, hubspot_note
    source_id = Column(String, nullable=False)
    subject = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    snippet = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="docs")
    chunks = relationship("Chunk", back_populates="doc", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_doc_user_source', 'user_id', 'source'),
        Index('idx_doc_source_id', 'source_id'),
    )

class Chunk(Base):
    __tablename__ = "chunks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_id = Column(String, ForeignKey("docs.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    # embedding = Column(Vector(1536), nullable=True)  # Commented out for testing without pgvector
    embedding_text = Column(Text, nullable=True)  # Store embedding as text for now
    idx = Column(Integer, nullable=False)  # Position in document
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    doc = relationship("Doc", back_populates="chunks")
    
    # Indexes
    __table_args__ = (
        # Index('idx_chunk_user_embedding', 'user_id', 'embedding', postgresql_using='ivfflat', postgresql_with={'lists': 100}),  # Commented out
        Index('idx_chunk_doc_idx', 'doc_id', 'idx'),
    )

class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # gmail, calendar, hubspot
    resource_id = Column(String, nullable=True)  # Resource ID from Google or HubSpot
    channel_id = Column(String, nullable=True)  # Channel ID for Google push notifications
    expiration = Column(DateTime(timezone=True), nullable=True)  # When subscription expires
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="webhook_subscriptions")
    
    # Indexes
    __table_args__ = (
        Index('idx_webhook_user_provider', 'user_id', 'provider'),
        Index('idx_webhook_channel', 'channel_id'),
    )

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    provider = Column(String, nullable=False)  # gmail, calendar, hubspot
    event_type = Column(String, nullable=False)  # new_email, calendar_update, contact_created, etc.
    resource_id = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    processed = Column(Boolean, default=False, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_webhook_event_processed', 'processed', 'created_at'),
        Index('idx_webhook_event_user', 'user_id'),
    )

class SyncState(Base):
    __tablename__ = "sync_states"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # gmail, calendar, hubspot
    resource_type = Column(String, nullable=False)  # emails, events, contacts, notes
    last_sync_token = Column(String, nullable=True)  # Sync token for incremental sync
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="sync_states")
    
    # Indexes
    __table_args__ = (
        Index('idx_sync_state_user_provider', 'user_id', 'provider', 'resource_type', unique=True),
    )
