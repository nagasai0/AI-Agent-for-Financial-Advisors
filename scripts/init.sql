-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create database if it doesn't exist (this would be run manually)
-- CREATE DATABASE financial_advisor_agent;

-- The tables will be created by SQLAlchemy models
-- This script is mainly for enabling the vector extension

-- Example index for vector similarity search (will be created by SQLAlchemy)
-- CREATE INDEX IF NOT EXISTS chunk_user_embedding_idx ON "chunks" USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
