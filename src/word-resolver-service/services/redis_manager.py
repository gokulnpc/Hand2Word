"""Redis Manager for sliding window state management"""
import json
import logging
from typing import List, Optional
from datetime import datetime
import redis
from config import settings
from models import LetterEntry, WordBuffer

logger = logging.getLogger(__name__)


class RedisManager:
    """Manages Redis connections and sliding window operations"""
    
    def __init__(self):
        self.client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=settings.redis_decode_responses,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        self._test_connection()
    
    def _test_connection(self):
        """Test Redis connection"""
        try:
            self.client.ping()
            logger.info(f"✓ Connected to Redis at {settings.redis_host}:{settings.redis_port}")
        except redis.ConnectionError as e:
            logger.error(f"✗ Failed to connect to Redis: {e}")
            raise
    
    # === Sliding Window Operations ===
    
    def get_window_key(self, session_id: str) -> str:
        """Get Redis key for session's sliding window"""
        return f"window:{session_id}"
    
    def get_word_buffer_key(self, session_id: str) -> str:
        """Get Redis key for session's word buffer"""
        return f"word:{session_id}"
    
    def push_letter(self, session_id: str, entry: LetterEntry) -> None:
        """
        Push a letter entry to the sliding window (right side of deque).
        Also sets TTL to prevent stale sessions.
        """
        key = self.get_window_key(session_id)
        value = entry.model_dump_json()
        
        # Add to right side of deque
        self.client.rpush(key, value)
        
        # Set TTL to 5 minutes to auto-cleanup inactive sessions
        self.client.expire(key, 300)
        
        logger.debug(f"Pushed letter '{entry.char}' (conf: {entry.confidence:.2f}) to {session_id}")
    
    def get_window(self, session_id: str) -> List[LetterEntry]:
        """
        Get all entries in the sliding window.
        Returns entries in chronological order (oldest first).
        """
        key = self.get_window_key(session_id)
        entries_json = self.client.lrange(key, 0, -1)
        
        return [LetterEntry.model_validate_json(e) for e in entries_json]
    
    def prune_window(self, session_id: str, cutoff_timestamp: float) -> int:
        """
        Remove entries older than cutoff_timestamp from the left side.
        Returns number of entries removed.
        """
        key = self.get_window_key(session_id)
        removed_count = 0
        
        while True:
            # Peek at leftmost (oldest) entry
            entry_json = self.client.lindex(key, 0)
            if not entry_json:
                break  # Empty list
            
            entry = LetterEntry.model_validate_json(entry_json)
            
            if entry.timestamp < cutoff_timestamp:
                # Remove from left
                self.client.lpop(key)
                removed_count += 1
            else:
                break  # Rest are newer
        
        if removed_count > 0:
            logger.debug(f"Pruned {removed_count} old entries from {session_id}")
        
        return removed_count
    
    def clear_window(self, session_id: str) -> None:
        """Clear entire sliding window for session"""
        key = self.get_window_key(session_id)
        self.client.delete(key)
        logger.debug(f"Cleared window for {session_id}")
    
    # === Word Buffer Operations ===
    
    def get_word_buffer(self, session_id: str, user_id: str) -> WordBuffer:
        """Get or create word buffer for session"""
        key = self.get_word_buffer_key(session_id)
        data = self.client.get(key)
        
        if data:
            return WordBuffer.model_validate_json(data)
        else:
            # Create new buffer
            buffer = WordBuffer(session_id=session_id, user_id=user_id)
            self.set_word_buffer(buffer)
            return buffer
    
    def set_word_buffer(self, buffer: WordBuffer) -> None:
        """Save word buffer to Redis"""
        key = self.get_word_buffer_key(buffer.session_id)
        self.client.setex(key, 300, buffer.model_dump_json())  # 5 min TTL
    
    def append_to_word(self, session_id: str, user_id: str, char: str) -> WordBuffer:
        """Append a letter to the word buffer"""
        buffer = self.get_word_buffer(session_id, user_id)
        buffer.letters.append(char)
        buffer.last_commit_time = datetime.now().timestamp()
        self.set_word_buffer(buffer)
        
        logger.info(f"✓ Committed '{char}' → word: '{buffer.current_word}' ({session_id})")
        return buffer
    
    def clear_word_buffer(self, session_id: str) -> None:
        """Clear word buffer after finalization"""
        key = self.get_word_buffer_key(session_id)
        self.client.delete(key)
        logger.debug(f"Cleared word buffer for {session_id}")
    
    # === Cleanup ===
    
    def cleanup_session(self, session_id: str) -> None:
        """Clean up all Redis data for a session"""
        self.clear_window(session_id)
        self.clear_word_buffer(session_id)
        logger.info(f"Cleaned up session {session_id}")

