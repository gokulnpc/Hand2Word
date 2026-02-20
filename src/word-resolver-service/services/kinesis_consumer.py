"""Kinesis Consumer for letter-stream events"""
import json
import logging
import signal
import sys
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from config import settings
from models import LetterPrediction
from services.redis_manager import RedisManager
from services.commit_engine import CommitEngine
from services.word_resolver import WordResolver

logger = logging.getLogger(__name__)

# Global shutdown flag
shutdown_flag = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_flag
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_flag = True


class KinesisConsumer:
    """
    Consumes letter predictions from asl-letters-stream.
    Processes each prediction through commit engine and word resolver.
    """
    
    def __init__(self):
        self.kinesis_client = boto3.client('kinesis', region_name=settings.aws_region)
        self.lambda_client = boto3.client('lambda', region_name=settings.aws_region)
        self.stream_name = settings.letters_stream_name
        
        # Initialize services
        self.redis_manager = RedisManager()
        self.commit_engine = CommitEngine(self.redis_manager)
        self.word_resolver = WordResolver()
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info(f"✓ Kinesis consumer initialized for {self.stream_name}")
        logger.info(f"✓ Outbound Lambda: {settings.outbound_lambda_name}")
    
    def get_shard_iterator(self, shard_id: str, iterator_type: str = 'LATEST') -> Optional[str]:
        """Get shard iterator for reading records"""
        try:
            response = self.kinesis_client.get_shard_iterator(
                StreamName=self.stream_name,
                ShardId=shard_id,
                ShardIteratorType=iterator_type
            )
            return response['ShardIterator']
        except ClientError as e:
            logger.error(f"Error getting shard iterator: {e}")
            return None
    
    def get_records(self, shard_iterator: str, limit: int = 100) -> tuple:
        """
        Get records from Kinesis stream.
        Returns (records, next_shard_iterator)
        """
        try:
            response = self.kinesis_client.get_records(
                ShardIterator=shard_iterator,
                Limit=limit
            )
            return response['Records'], response.get('NextShardIterator')
        except ClientError as e:
            logger.error(f"Error getting records: {e}")
            return [], None
    
    def process_record(self, record: dict) -> None:
        """Process a single letter prediction record"""
        try:
            # Parse record
            data = json.loads(record['Data'])
            prediction = LetterPrediction(**data)
            
            session_id = prediction.session_id
            
            # Handle skip events (pause indicator)
            if prediction.event_type == 'skip':
                logger.debug(f"Skip event for {session_id}: {prediction.skip_reason}")
                
                # Check if we should finalize word
                if self.commit_engine.check_pause(session_id):
                    self._finalize_word(session_id, search_method='skip_event')
                
                return
            
            # Handle letter prediction
            if prediction.event_type == 'prediction' and prediction.prediction:
                char = prediction.prediction
                confidence = prediction.confidence or 0.0
                # Convert datetime to Unix timestamp (float)
                timestamp_dt = record.get('ApproximateArrivalTimestamp', 0)
                timestamp = timestamp_dt.timestamp() if hasattr(timestamp_dt, 'timestamp') else timestamp_dt
                
                # Process through commit engine
                buffer = self.commit_engine.process_letter(
                    session_id=session_id,
                    user_id=prediction.session_id,  # Using session_id as user_id for now
                    char=char,
                    confidence=confidence,
                    timestamp=timestamp
                )
                
                # Check for pause after processing
                if self.commit_engine.check_pause(session_id):
                    self._finalize_word(session_id, search_method='fuzzy')
        
        except Exception as e:
            logger.error(f"Error processing record: {e}")
    
    def _send_to_outbound_lambda(self, session_id: str, resolved_word: dict) -> None:
        """
        Send resolved word to outbound Lambda for delivery to WebSocket client.
        """
        try:
            payload = {
                'session_id': session_id,
                'resolved_word': resolved_word
            }
            
            response = self.lambda_client.invoke(
                FunctionName=settings.outbound_lambda_name,
                InvocationType='Event',  # Async invocation
                Payload=json.dumps(payload)
            )
            
            logger.debug(f"✓ Invoked outbound Lambda for session {session_id}: {response['StatusCode']}")
        
        except ClientError as e:
            logger.error(f"Error invoking outbound Lambda: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending to outbound Lambda: {e}")
    
    def _check_all_sessions_for_pause(self) -> None:
        """
        Check all active sessions for pause condition.
        This is a periodic check to finalize words even when no new records arrive.
        """
        try:
            # Get all word buffer keys from Redis
            pattern = "word:*"
            keys = list(self.redis_manager.client.scan_iter(match=pattern))
            
            for key in keys:
                # Extract session_id from key (format: "word:SESSION_ID")
                session_id = key.split(":", 1)[1] if ":" in key else key
                
                # Check if this session needs word finalization
                if self.commit_engine.check_pause(session_id):
                    self._finalize_word(session_id, search_method='fuzzy')
        
        except Exception as e:
            logger.debug(f"Error checking sessions for pause: {e}")
    
    def _finalize_word(self, session_id: str, search_method: str = 'fuzzy') -> None:
        """
        Finalize and resolve word, then clean up session state.
        """
        try:
            # Get word buffer
            buffer = self.redis_manager.get_word_buffer(session_id, session_id)
            
            if not buffer.letters:
                logger.debug(f"No word to finalize for {session_id}")
                return
            
            # Resolve word
            resolved = self.word_resolver.resolve_word(buffer, search_method)
            
            if resolved.all_results:
                logger.info(f"📤 Finalized word: '{resolved.raw_word}' ({session_id})")
                logger.info(f"   Top {len(resolved.all_results)} results:")
                for i, result in enumerate(resolved.all_results[:5], 1):
                    logger.info(
                        f"     {i}. {result.surface:20} (atlas: {result.atlas_score:.3f}, "
                        f"alias_conf: {result.alias_confidence:.3f}, hybrid: {result.hybrid_score:.3f})"
                    )
            else:
                logger.info(f"📤 Finalized word: '{resolved.raw_word}' → UNRESOLVED ({session_id})")
            
            # Send resolved word to outbound Lambda → API Gateway → Client
            try:
                # Convert Pydantic model to dict for JSON serialization
                resolved_dict = resolved.model_dump()
                self._send_to_outbound_lambda(session_id, resolved_dict)
                logger.info(f"✓ Sent resolved word to outbound Lambda for session {session_id}")
            except Exception as e:
                logger.error(f"Error sending resolved word to outbound Lambda: {e}")
            
            # Clean up session state
            self.redis_manager.clear_word_buffer(session_id)
            self.redis_manager.clear_window(session_id)
        
        except Exception as e:
            logger.error(f"Error finalizing word for {session_id}: {e}")
    
    def run(self):
        """Main consumer loop"""
        global shutdown_flag
        
        logger.info(f"Starting Kinesis consumer for {self.stream_name}")
        
        try:
            # Get shard list
            response = self.kinesis_client.describe_stream(StreamName=self.stream_name)
            shards = response['StreamDescription']['Shards']
            
            logger.info(f"Found {len(shards)} shard(s) in {self.stream_name}")
            
            # For simplicity, consume from first shard only
            # In production, use KCL or parallel consumers
            shard_id = shards[0]['ShardId']
            shard_iterator = self.get_shard_iterator(shard_id, 'LATEST')
            
            if not shard_iterator:
                logger.error("Failed to get shard iterator")
                return
            
            logger.info(f"✓ Consuming from shard {shard_id}")
            
            # Main loop
            import time
            last_pause_check = time.time()
            pause_check_interval = 1.0  # Check for pauses every 1 second
            
            while not shutdown_flag:
                records, next_iterator = self.get_records(shard_iterator, limit=100)
                
                if records:
                    logger.info(f"Processing {len(records)} record(s)")
                    for record in records:
                        self.process_record(record)
                
                # Periodic pause check for active sessions (even when no records)
                current_time = time.time()
                if current_time - last_pause_check >= pause_check_interval:
                    # Check all active sessions for pause (simplified: check if any keys exist)
                    # In production, maintain a set of active session_ids
                    self._check_all_sessions_for_pause()
                    last_pause_check = current_time
                
                # Update iterator
                if next_iterator:
                    shard_iterator = next_iterator
                else:
                    logger.warning("No next iterator, stopping")
                    break
                
                # Brief sleep to avoid throttling
                time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"Error in consumer loop: {e}")
        
        finally:
            logger.info("Shutting down consumer...")
            self.word_resolver.close()
    
    def close(self):
        """Cleanup resources"""
        self.word_resolver.close()
        logger.info("Consumer closed")

