"""Unit tests for RedisManager"""
import pytest
from datetime import datetime
from models import LetterEntry, WordBuffer


# These tests require a running Redis instance
# Skip if Redis is not available
pytest_plugins = ('pytest_asyncio',)


def test_letter_entry_age():
    """Test LetterEntry age calculation"""
    now = datetime.now().timestamp()
    entry = LetterEntry(char="A", confidence=0.9, timestamp=now - 0.1)
    
    # Age should be ~100ms
    assert 90 <= entry.age_ms <= 110


def test_word_buffer_current_word():
    """Test WordBuffer current_word property"""
    buffer = WordBuffer(
        session_id="test",
        user_id="user1",
        letters=["A", "W", "S"]
    )
    
    assert buffer.current_word == "AWS"


def test_word_buffer_empty():
    """Test empty WordBuffer"""
    buffer = WordBuffer(
        session_id="test",
        user_id="user1",
        letters=[]
    )
    
    assert buffer.current_word == ""
    assert buffer.time_since_last_commit_ms is None


def test_word_buffer_time_since_commit():
    """Test time_since_last_commit_ms calculation"""
    now = datetime.now().timestamp()
    
    buffer = WordBuffer(
        session_id="test",
        user_id="user1",
        letters=["A"],
        last_commit_time=now - 0.2  # 200ms ago
    )
    
    time_since = buffer.time_since_last_commit_ms
    assert time_since is not None
    assert 190 <= time_since <= 210


# Integration tests (require Redis)
class TestRedisManagerIntegration:
    """
    Integration tests for RedisManager.
    These require a running Redis instance (e.g., docker run -p 6379:6379 redis:7-alpine)
    """
    
    @pytest.fixture
    def redis_manager(self):
        """Create RedisManager (skip if Redis not available)"""
        try:
            from services.redis_manager import RedisManager
            from config import settings
            
            # Override with localhost for testing
            original_host = settings.redis_host
            settings.redis_host = "localhost"
            
            manager = RedisManager()
            
            yield manager
            
            # Cleanup
            settings.redis_host = original_host
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    def test_push_and_get_window(self, redis_manager):
        """Test pushing letters to window and retrieving"""
        session_id = "test_session_1"
        
        # Clear any existing data
        redis_manager.clear_window(session_id)
        
        # Push letters
        now = datetime.now().timestamp()
        redis_manager.push_letter(session_id, LetterEntry(char="A", confidence=0.9, timestamp=now))
        redis_manager.push_letter(session_id, LetterEntry(char="B", confidence=0.8, timestamp=now + 0.05))
        
        # Get window
        window = redis_manager.get_window(session_id)
        
        assert len(window) == 2
        assert window[0].char == "A"
        assert window[1].char == "B"
        assert window[0].confidence == 0.9
    
    def test_prune_window(self, redis_manager):
        """Test pruning old entries from window"""
        session_id = "test_session_2"
        redis_manager.clear_window(session_id)
        
        now = datetime.now().timestamp()
        
        # Push entries with different timestamps
        redis_manager.push_letter(session_id, LetterEntry(char="A", confidence=0.9, timestamp=now - 0.3))  # 300ms ago
        redis_manager.push_letter(session_id, LetterEntry(char="B", confidence=0.8, timestamp=now - 0.1))  # 100ms ago
        redis_manager.push_letter(session_id, LetterEntry(char="C", confidence=0.9, timestamp=now))       # now
        
        # Prune entries older than 200ms
        cutoff = now - 0.2
        removed = redis_manager.prune_window(session_id, cutoff)
        
        assert removed == 1  # Should remove 'A'
        
        # Verify remaining
        window = redis_manager.get_window(session_id)
        assert len(window) == 2
        assert window[0].char == "B"
        assert window[1].char == "C"
    
    def test_word_buffer_operations(self, redis_manager):
        """Test word buffer save/load"""
        session_id = "test_session_3"
        user_id = "user1"
        
        # Append letters
        buffer = redis_manager.append_to_word(session_id, user_id, "H")
        assert buffer.current_word == "H"
        
        buffer = redis_manager.append_to_word(session_id, user_id, "I")
        assert buffer.current_word == "HI"
        
        # Retrieve
        loaded_buffer = redis_manager.get_word_buffer(session_id, user_id)
        assert loaded_buffer.current_word == "HI"
        assert loaded_buffer.session_id == session_id
        
        # Clear
        redis_manager.clear_word_buffer(session_id)
        new_buffer = redis_manager.get_word_buffer(session_id, user_id)
        assert new_buffer.current_word == ""
    
    def test_last_commit_tracking(self, redis_manager):
        """Test last commit tracking for deduplication"""
        session_id = "test_session_4"
        now = datetime.now().timestamp()
        
        # Set last commit
        redis_manager.set_last_commit(session_id, "A", now)
        
        # Retrieve
        last_commit = redis_manager.get_last_commit(session_id)
        assert last_commit is not None
        assert last_commit['char'] == "A"
        assert abs(last_commit['timestamp'] - now) < 0.01  # Within 10ms
    
    def test_cleanup_session(self, redis_manager):
        """Test full session cleanup"""
        session_id = "test_session_5"
        user_id = "user1"
        now = datetime.now().timestamp()
        
        # Create data
        redis_manager.push_letter(session_id, LetterEntry(char="X", confidence=0.9, timestamp=now))
        redis_manager.append_to_word(session_id, user_id, "Y")
        redis_manager.set_last_commit(session_id, "Z", now)
        
        # Cleanup
        redis_manager.cleanup_session(session_id)
        
        # Verify all cleared
        assert len(redis_manager.get_window(session_id)) == 0
        assert redis_manager.get_word_buffer(session_id, user_id).current_word == ""
        assert redis_manager.get_last_commit(session_id) is None

