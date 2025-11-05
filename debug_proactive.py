#!/usr/bin/env python3
"""
Proactive Agent Debug Script
Run this to start the proactive worker with enhanced debugging
"""
import os
import sys
import logging
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

# Set up enhanced logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('proactive_debug.log')
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Start proactive worker with debugging"""
    logger.info("Starting Proactive Agent Debug Mode")
    logger.info("=" * 50)
    
    try:
        from worker_proactive import ProactiveWorker
        
        # Create worker instance
        worker = ProactiveWorker()
        
        logger.info("ProactiveWorker created successfully")
        logger.info("Starting worker loop...")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 50)
        
        # Start the worker
        worker.start()
        
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Error starting worker: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()
