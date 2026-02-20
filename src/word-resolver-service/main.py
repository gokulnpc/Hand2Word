#!/usr/bin/env python3
"""
Word Resolver Service - Main Entry Point
Consumes letter predictions from Kinesis, applies commit rules,
and resolves words using MongoDB Atlas fuzzy search.
"""

import logging
import sys
from config import settings
from services.kinesis_consumer import KinesisConsumer

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    logger.info("=" * 80)
    logger.info(f"Starting {settings.service_name}")
    logger.info("=" * 80)
    logger.info(f"AWS Region: {settings.aws_region}")
    logger.info(f"Letters Stream: {settings.letters_stream_name}")
    logger.info(f"Redis: {settings.redis_host}:{settings.redis_port}")
    logger.info(f"Window: {settings.window_duration_ms}ms")
    logger.info(f"Stability: {settings.stability_duration_ms}ms")
    logger.info(f"Max Consecutive: {settings.max_consecutive_same} same letters")
    logger.info(f"Pause: {settings.pause_duration_ms}ms")
    logger.info("=" * 80)
    
    try:
        consumer = KinesisConsumer()
        consumer.run()
    except KeyboardInterrupt:
        logger.info("\nReceived keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()

