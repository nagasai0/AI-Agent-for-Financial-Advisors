# Single service Dockerfile - Backend with static frontend
FROM --platform=linux/amd64 python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY backend/requirements.txt ./backend-requirements.txt
COPY workers/requirements.txt ./worker-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip wheel setuptools --root-user-action=ignore
RUN pip install --no-cache-dir -r backend-requirements.txt --root-user-action=ignore
RUN pip install --no-cache-dir -r worker-requirements.txt --root-user-action=ignore

# Copy application code
COPY backend/ ./backend/
COPY workers/ ./workers/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app

# Switch to non-root user
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the backend server (now includes proactive worker)
CMD ["python", "backend/main.py"]
