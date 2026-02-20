#!/usr/bin/env python3
"""
Letter ASL Model Serving Service - Kinesis Consumer/Producer
Reads hand landmarks from asl-landmarks-stream, performs letter ASL prediction,
and writes results to asl-letters-stream using Enhanced Fan-Out (EFO).
"""

import logging
import json
import os
import time
import signal
import sys
import random
from datetime import datetime
from typing import Optional
import boto3
from botocore.exceptions import ClientError

from services.asl_service import LetterASLService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
LANDMARKS_STREAM_NAME = os.environ.get('LANDMARKS_STREAM_NAME', 'asl-landmarks-stream')
LETTERS_STREAM_NAME = os.environ.get('LETTERS_STREAM_NAME', 'asl-letters-stream')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
POLLING_INTERVAL = int(os.environ.get('POLLING_INTERVAL', '1'))  # seconds

# Initialize AWS clients
kinesis_client = boto3.client('kinesis', region_name=AWS_REGION)

# Global flag for graceful shutdown
shutdown_flag = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_flag
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_flag = True


def get_shard_iterator(stream_name: str, shard_id: str, iterator_type: str = 'LATEST') -> Optional[str]:
    """
    Get a shard iterator for reading from Kinesis stream.
    
    Args:
        stream_name: Name of the Kinesis stream
        shard_id: ID of the shard to read from
        iterator_type: Type of iterator (LATEST, TRIM_HORIZON, etc.)
        
    Returns:
        Shard iterator string or None if error
    """
    try:
        response = kinesis_client.get_shard_iterator(
            StreamName=stream_name,
            ShardId=shard_id,
            ShardIteratorType=iterator_type
        )
        return response['ShardIterator']
    except ClientError as e:
        logger.error(f"Error getting shard iterator: {e}")
        return None


def get_records(shard_iterator: str, limit: int = 100) -> tuple:
    """
    Get records from Kinesis stream.
    
    Args:
        shard_iterator: Current shard iterator
        limit: Maximum number of records to retrieve
        
    Returns:
        Tuple of (records, next_shard_iterator)
    """
    try:
        response = kinesis_client.get_records(
            ShardIterator=shard_iterator,
            Limit=limit
        )
        return response['Records'], response.get('NextShardIterator')
    except ClientError as e:
        logger.error(f"Error getting records: {e}")
        return [], None


def put_prediction_to_kinesis(session_id: str, connection_id: str, prediction_data: dict) -> bool:
    """
    Write prediction result or metadata event to letters stream.
    
    Args:
        session_id: Session ID for partitioning
        connection_id: WebSocket connection ID
        prediction_data: Dictionary containing prediction results or skip metadata
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if this was skipped (multi-hand or no hands)
        if prediction_data.get('skipped', False):
            # Write metadata event instead of prediction
            record = {
                'session_id': session_id,
                'connection_id': connection_id,
                'timestamp': datetime.utcnow().isoformat(),
                'event_type': 'skip',
                'skip_reason': prediction_data['skip_reason'],
                'multi_hand': prediction_data.get('multi_hand', False),
                'handedness': prediction_data.get('handedness'),
                'processing_time_ms': prediction_data.get('processing_time_ms', 0),
                'metadata': {
                    'source': 'letter-model-sevice',
                    'message': 'Multi-hand detected - likely word-level sign' if prediction_data.get('multi_hand') else 'No hands detected'
                }
            }
            
            response = kinesis_client.put_record(
                StreamName=LETTERS_STREAM_NAME,
                Data=json.dumps(record),
                PartitionKey=session_id
            )
            
            logger.info(f"Wrote skip event to {LETTERS_STREAM_NAME}: {prediction_data['skip_reason']} "
                       f"(session: {session_id}, shard: {response['ShardId']})")
        else:
            # Write normal prediction
            record = {
                'session_id': session_id,
                'connection_id': connection_id,
                'timestamp': datetime.utcnow().isoformat(),
                'event_type': 'prediction',
                'prediction': prediction_data['prediction'],
                'confidence': prediction_data['confidence'],
                'handedness': prediction_data.get('handedness'),  # Which hand was used
                'multi_hand': prediction_data.get('multi_hand', False),
                'processing_time_ms': prediction_data.get('processing_time_ms', 0),
                'metadata': {
                    'source': 'letter-model-sevice',
                    'model_type': 'keypoint_classifier',
                    'fingerspelling': True  # Single-hand letter prediction
                }
            }
            
            response = kinesis_client.put_record(
                StreamName=LETTERS_STREAM_NAME,
                Data=json.dumps(record),
                PartitionKey=session_id
            )
            
            logger.info(f"Wrote prediction to {LETTERS_STREAM_NAME}: {prediction_data['prediction']} "
                       f"(confidence: {prediction_data['confidence']:.2f}, "
                       f"hand: {prediction_data.get('handedness', 'unknown')}, "
                       f"session: {session_id}, "
                       f"shard: {response['ShardId']})")
        
        return True
        
    except ClientError as e:
        logger.error(f"Error writing to Kinesis: {e}")
        return False


async def process_landmark_record(letter_asl_service: LetterASLService, record: dict) -> None:
    """
    Process a single landmark record from Kinesis.
    Extracts hand from full MediaPipe Holistic data and performs fingerspelling prediction.
    
    Args:
        letter_asl_service: Initialized Letter ASL service instance
        record: Kinesis record containing full holistic landmark data
    """
    try:
        # Decode record data
        data = json.loads(record['Data'])
        
        session_id = data.get('session_id', 'unknown')
        connection_id = data.get('connection_id', 'unknown')
        landmarks = data.get('landmarks', [])
        
        if not landmarks:
            logger.debug(f"No landmarks in record for session {session_id}")
            return
        
        logger.debug(f"Processing holistic landmarks for session {session_id}, "
                    f"{len(landmarks)} values")
        #logger.info(f"Landmarks: {landmarks}")
        # Predict from holistic landmarks (includes hand extraction and filtering)
        start_time = time.time()
        result = await letter_asl_service.predict_from_landmarks(
            landmarks_list=landmarks,  # Full holistic array
            user_id=session_id
        )
        processing_time_ms = (time.time() - start_time) * 1000
        
        # The result already contains all necessary data including skip info
        prediction_data = {
            'prediction': result.get('prediction'),
            'confidence': result.get('confidence', 0.0),
            'processing_time_ms': round(processing_time_ms, 2),
            'handedness': result.get('handedness'),
            'multi_hand': result.get('multi_hand', False),
            'skipped': result.get('skipped', False),
            'skip_reason': result.get('skip_reason')
        }
        
        # Write prediction or metadata event to letters stream
        put_prediction_to_kinesis(session_id, connection_id, prediction_data)
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding record data: {e}")
    except Exception as e:
        logger.error(f"Error processing landmark record: {e}", exc_info=True)


def process_shard_with_efo_sync(letter_asl_service: LetterASLService, consumer_arn: str, shard_id: str) -> int:
    """
    Process a single shard using EFO subscription (synchronous version).
    This runs in a thread pool to avoid blocking the async event loop.
    
    EFO subscriptions have a 5-minute maximum duration, so we need to re-subscribe
    in a loop using continuation sequence numbers.
    
    Args:
        letter_asl_service: Initialized Letter ASL service instance
        consumer_arn: ARN of the registered EFO consumer
        shard_id: ID of the shard to process
        
    Returns:
        Number of records processed
    """
    global shutdown_flag
    records_processed = 0
    starting_position = {'Type': 'LATEST'}
    retry_count = 0
    max_retry_delay = 60  # Maximum retry delay in seconds
    
    logger.info(f"[{shard_id}] Starting EFO subscription loop (LATEST mode)...")
    
    # Keep re-subscribing until shutdown (EFO subscriptions expire after ~5 minutes)
    while not shutdown_flag:
        try:
            # Subscribe to shard with EFO (push-based)
            response = kinesis_client.subscribe_to_shard(
                ConsumerARN=consumer_arn,
                ShardId=shard_id,
                StartingPosition=starting_position
            )
            
            logger.info(f"[{shard_id}] EFO subscription active, waiting for records...")
            
            # Reset retry counter on successful connection
            retry_count = 0
            
            # Process events from the subscription (long-lived streaming connection)
            continuation_sequence = None
            for event in response['EventStream']:
                if shutdown_flag:
                    logger.info(f"[{shard_id}] Shutdown requested, ending subscription")
                    break
                
                if 'SubscribeToShardEvent' in event:
                    shard_event = event['SubscribeToShardEvent']
                    records = shard_event['Records']
                    continuation_sequence = shard_event.get('ContinuationSequenceNumber')
                    
                    # Process each record - note: we call the async function synchronously here
                    # since we're in a thread pool
                    import asyncio
                    for record in records:
                        if shutdown_flag:
                            break
                        # Run async processing in event loop
                        try:
                            # Create a new event loop for this thread
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(process_landmark_record(letter_asl_service, record))
                            loop.close()
                        except Exception as e:
                            logger.error(f"[{shard_id}] Error processing record: {e}")
                        records_processed += 1
                    
                    if records:
                        logger.info(f"[{shard_id}] Processed {len(records)} record(s) (total: {records_processed})")
                    else:
                        # Log heartbeat events (no records but subscription is alive)
                        logger.debug(f"[{shard_id}] Heartbeat event (no records)")
            
            # If we have a continuation sequence, use it for the next subscription
            if continuation_sequence and not shutdown_flag:
                logger.info(f"[{shard_id}] Subscription expired (~5min), re-subscribing from continuation point...")
                starting_position = {
                    'Type': 'AFTER_SEQUENCE_NUMBER',  # Use AFTER to avoid re-processing last record
                    'SequenceNumber': continuation_sequence
                }
            elif not shutdown_flag:
                # No continuation means the shard ended (unlikely for active stream)
                logger.debug(f"[{shard_id}] Subscription ended without continuation. Waiting before retry...")
                time.sleep(5)
                starting_position = {'Type': 'LATEST'}
                
        except ClientError as e:
            if not shutdown_flag:
                retry_count += 1
                # Exponential backoff with jitter: base_delay * 2^retry_count + random jitter
                base_delay = 2
                exponential_delay = min(base_delay * (2 ** retry_count), max_retry_delay)
                jitter = random.uniform(0, exponential_delay * 0.1)  # 10% jitter
                retry_delay = exponential_delay + jitter
                
                logger.error(f"[{shard_id}] Error in EFO subscription: {e}")
                logger.info(f"[{shard_id}] Retry {retry_count}: waiting {retry_delay:.1f}s before retry...")
                time.sleep(retry_delay)
        except Exception as e:
            if not shutdown_flag:
                retry_count += 1
                base_delay = 2
                exponential_delay = min(base_delay * (2 ** retry_count), max_retry_delay)
                jitter = random.uniform(0, exponential_delay * 0.1)
                retry_delay = exponential_delay + jitter
                
                logger.error(f"[{shard_id}] Unexpected error: {e}", exc_info=True)
                logger.info(f"[{shard_id}] Retry {retry_count}: waiting {retry_delay:.1f}s before retry...")
                time.sleep(retry_delay)
    
    logger.info(f"[{shard_id}] Subscription loop ended. Total processed: {records_processed} records")
    return records_processed


async def process_shard_with_efo(letter_asl_service: LetterASLService, consumer_arn: str, shard_id: str) -> int:
    """
    Async wrapper for processing a shard using EFO subscription.
    Runs the synchronous boto3 call in a thread pool to avoid blocking.
    """
    import asyncio
    # Run the blocking boto3 subscribe_to_shard in a thread pool
    return await asyncio.to_thread(process_shard_with_efo_sync, letter_asl_service, consumer_arn, shard_id)


async def consume_and_process_efo(letter_asl_service: LetterASLService) -> None:
    """
    Main consumer loop using Enhanced Fan-Out (EFO): subscribe to landmarks stream with push-based delivery.
    
    Args:
        letter_asl_service: Initialized Letter ASL service instance
    """
    global shutdown_flag
    
    # Register stream consumer for Enhanced Fan-Out
    consumer_name = f"letter-asl-service-{os.environ.get('HOSTNAME', 'local')}"
    
    try:
        # Register consumer (or get existing)
        try:
            response = kinesis_client.register_stream_consumer(
                StreamARN=get_stream_arn(LANDMARKS_STREAM_NAME),
                ConsumerName=consumer_name
            )
            consumer_arn = response['Consumer']['ConsumerARN']
            logger.info(f"Registered EFO consumer: {consumer_name}")
            logger.info(f"Consumer ARN: {consumer_arn}")
            
            # Wait for consumer to become ACTIVE
            while True:
                consumer_status = kinesis_client.describe_stream_consumer(
                    StreamARN=get_stream_arn(LANDMARKS_STREAM_NAME),
                    ConsumerName=consumer_name
                )
                status = consumer_status['ConsumerDescription']['ConsumerStatus']
                if status == 'ACTIVE':
                    logger.info(f"Consumer is ACTIVE")
                    break
                logger.info(f"Waiting for consumer to become ACTIVE (current: {status})...")
                time.sleep(2)
                
        except kinesis_client.exceptions.ResourceInUseException:
            # Consumer already exists
            consumer_status = kinesis_client.describe_stream_consumer(
                StreamARN=get_stream_arn(LANDMARKS_STREAM_NAME),
                ConsumerName=consumer_name
            )
            consumer_arn = consumer_status['ConsumerDescription']['ConsumerARN']
            logger.info(f"Using existing EFO consumer: {consumer_name}")
            logger.info(f"Consumer ARN: {consumer_arn}")
        
        # Get list of shards
        stream_description = kinesis_client.describe_stream(StreamName=LANDMARKS_STREAM_NAME)
        shards = stream_description['StreamDescription']['Shards']
        logger.info(f"Found {len(shards)} shard(s) in {LANDMARKS_STREAM_NAME}")
        
        # Subscribe to each shard using EFO with asyncio tasks for concurrent processing
        logger.info("Starting Enhanced Fan-Out (EFO) subscriptions...")
        
        # Create async tasks for each shard
        import asyncio
        tasks = []
        for shard in shards:
            shard_id = shard['ShardId']
            task = asyncio.create_task(
                process_shard_with_efo(letter_asl_service, consumer_arn, shard_id)
            )
            tasks.append(task)
            logger.info(f"Created EFO subscription task for shard {shard_id}")
        
        # Wait for all shard tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Sum up total records processed
        total_records = sum(r for r in results if isinstance(r, int))
        logger.info(f"EFO consumer loop ended. Total records processed: {total_records}")
        
    except Exception as e:
        logger.error(f"Fatal error in EFO consumer: {e}", exc_info=True)
    finally:
        # Deregister consumer on shutdown
        try:
            kinesis_client.deregister_stream_consumer(
                StreamARN=get_stream_arn(LANDMARKS_STREAM_NAME),
                ConsumerName=consumer_name
            )
            logger.info(f"Deregistered EFO consumer: {consumer_name}")
        except Exception as e:
            logger.debug(f"Error deregistering consumer: {e}")


def get_stream_arn(stream_name: str) -> str:
    """
    Get the ARN for a Kinesis stream.
    
    Args:
        stream_name: Name of the stream
        
    Returns:
        Stream ARN
    """
    try:
        response = kinesis_client.describe_stream(StreamName=stream_name)
        return response['StreamDescription']['StreamARN']
    except ClientError as e:
        logger.error(f"Error getting stream ARN: {e}")
        raise


def main():
    """Main entry point for the Kinesis consumer service."""
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("=" * 60)
    logger.info("Letter ASL Model Serving Service - EFO Consumer/Producer")
    logger.info("=" * 60)
    logger.info(f"Landmarks Stream: {LANDMARKS_STREAM_NAME}")
    logger.info(f"Letters Stream: {LETTERS_STREAM_NAME}")
    logger.info(f"AWS Region: {AWS_REGION}")
    logger.info(f"Consumer Mode: Enhanced Fan-Out (EFO) - Push-based")
    logger.info("=" * 60)
    
    # Initialize Letter ASL service
    logger.info("Initializing Letter ASL prediction service...")
    try:
        letter_asl_service = LetterASLService()
        logger.info("✓ Letter ASL service initialized successfully")
    except Exception as e:
        logger.error(f"✗ Failed to initialize Letter ASL service: {e}")
        sys.exit(1)
    
    # Start consuming and processing with EFO
    try:
        import asyncio
        asyncio.run(consume_and_process_efo(letter_asl_service))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        sys.exit(1)
    
    logger.info("Service stopped gracefully")
    sys.exit(0)


if __name__ == "__main__":
    main()
