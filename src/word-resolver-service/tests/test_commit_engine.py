"""Unit tests for CommitEngine"""
import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock
from services.commit_engine import CommitEngine
from services.redis_manager import RedisManager
from models import LetterEntry, WordBuffer


@pytest.fixture
def mock_redis():
    """Mock Redis manager"""
    redis = Mock(spec=RedisManager)
    redis.push_letter = MagicMock()
    redis.prune_window = MagicMock(return_value=0)
    redis.get_window = MagicMock(return_value=[])
    redis.append_to_word = MagicMock()
    redis.set_last_commit = MagicMock()
    redis.get_last_commit = MagicMock(return_value=None)
    redis.get_word_buffer = MagicMock()
    return redis


@pytest.fixture
def commit_engine(mock_redis):
    """Create CommitEngine with mocked Redis"""
    return CommitEngine(mock_redis)


class TestCommitEngine:
    """Test cases for CommitEngine"""
    
    def test_empty_window_no_commit(self, commit_engine, mock_redis):
        """Empty window should not commit"""
        mock_redis.get_window.return_value = []
        
        result = commit_engine.process_letter(
            session_id="test",
            user_id="user1",
            char="A",
            confidence=0.9,
            timestamp=datetime.now().timestamp()
        )
        
        assert result is None
        mock_redis.append_to_word.assert_not_called()
    
    def test_low_confidence_ignored(self, commit_engine, mock_redis):
        """Low confidence predictions should be ignored"""
        now = datetime.now().timestamp()
        
        # All low confidence entries
        mock_redis.get_window.return_value = [
            LetterEntry(char="A", confidence=0.2, timestamp=now),
            LetterEntry(char="A", confidence=0.1, timestamp=now),
        ]
        
        result = commit_engine.process_letter(
            session_id="test",
            user_id="user1",
            char="A",
            confidence=0.2,
            timestamp=now
        )
        
        assert result is None
    
    def test_unstable_prediction_no_commit(self, commit_engine, mock_redis):
        """Prediction not stable long enough should not commit"""
        now = datetime.now().timestamp()
        
        # High confidence but not stable (< 135ms)
        mock_redis.get_window.return_value = [
            LetterEntry(char="A", confidence=0.9, timestamp=now - 0.05),  # 50ms ago
            LetterEntry(char="A", confidence=0.9, timestamp=now),
        ]
        
        result = commit_engine.process_letter(
            session_id="test",
            user_id="user1",
            char="A",
            confidence=0.9,
            timestamp=now
        )
        
        assert result is None
        mock_redis.append_to_word.assert_not_called()
    
    def test_stable_prediction_commits(self, commit_engine, mock_redis):
        """Stable prediction with high confidence should commit"""
        now = datetime.now().timestamp()
        
        # Stable for 150ms (> 135ms requirement)
        mock_redis.get_window.return_value = [
            LetterEntry(char="A", confidence=0.9, timestamp=now - 0.15),
            LetterEntry(char="A", confidence=0.8, timestamp=now - 0.10),
            LetterEntry(char="A", confidence=0.9, timestamp=now - 0.05),
            LetterEntry(char="A", confidence=0.9, timestamp=now),
        ]
        
        mock_redis.append_to_word.return_value = WordBuffer(
            session_id="test",
            user_id="user1",
            letters=["A"]
        )
        
        result = commit_engine.process_letter(
            session_id="test",
            user_id="user1",
            char="A",
            confidence=0.9,
            timestamp=now
        )
        
        assert result is not None
        mock_redis.append_to_word.assert_called_once()
        assert mock_redis.append_to_word.call_args[0] == ("test", "user1", "A")
    
    def test_confidence_weighted_voting(self, commit_engine, mock_redis):
        """Should select character with highest aggregate confidence"""
        now = datetime.now().timestamp()
        
        # B has higher aggregate confidence (0.9 + 0.8 = 1.7) vs A (0.6 + 0.6 = 1.2)
        mock_redis.get_window.return_value = [
            LetterEntry(char="A", confidence=0.6, timestamp=now - 0.15),
            LetterEntry(char="B", confidence=0.9, timestamp=now - 0.14),
            LetterEntry(char="A", confidence=0.6, timestamp=now - 0.10),
            LetterEntry(char="B", confidence=0.8, timestamp=now - 0.05),
            LetterEntry(char="B", confidence=0.7, timestamp=now),
        ]
        
        mock_redis.append_to_word.return_value = WordBuffer(
            session_id="test",
            user_id="user1",
            letters=["B"]
        )
        
        result = commit_engine.process_letter(
            session_id="test",
            user_id="user1",
            char="B",
            confidence=0.7,
            timestamp=now
        )
        
        assert result is not None
        # Should commit 'B', not 'A'
        assert mock_redis.append_to_word.call_args[0][2] == "B"
    
    def test_deduplication_prevents_repeat(self, commit_engine, mock_redis):
        """Should not commit same letter within dedupe threshold"""
        now = datetime.now().timestamp()
        
        # Last commit was 'A' 100ms ago (< 250ms threshold)
        mock_redis.get_last_commit.return_value = {
            "char": "A",
            "timestamp": now - 0.1
        }
        
        # Stable 'A' prediction
        mock_redis.get_window.return_value = [
            LetterEntry(char="A", confidence=0.9, timestamp=now - 0.15),
            LetterEntry(char="A", confidence=0.9, timestamp=now),
        ]
        
        result = commit_engine.process_letter(
            session_id="test",
            user_id="user1",
            char="A",
            confidence=0.9,
            timestamp=now
        )
        
        # Should not commit due to deduplication
        assert result is None
        mock_redis.append_to_word.assert_not_called()
    
    def test_deduplication_allows_after_threshold(self, commit_engine, mock_redis):
        """Should commit same letter after dedupe threshold"""
        now = datetime.now().timestamp()
        
        # Last commit was 'A' 300ms ago (> 250ms threshold)
        mock_redis.get_last_commit.return_value = {
            "char": "A",
            "timestamp": now - 0.3
        }
        
        # Stable 'A' prediction
        mock_redis.get_window.return_value = [
            LetterEntry(char="A", confidence=0.9, timestamp=now - 0.15),
            LetterEntry(char="A", confidence=0.9, timestamp=now),
        ]
        
        mock_redis.append_to_word.return_value = WordBuffer(
            session_id="test",
            user_id="user1",
            letters=["A", "A"]
        )
        
        result = commit_engine.process_letter(
            session_id="test",
            user_id="user1",
            char="A",
            confidence=0.9,
            timestamp=now
        )
        
        # Should commit (double letter case)
        assert result is not None
        mock_redis.append_to_word.assert_called_once()
    
    def test_check_pause_no_word(self, commit_engine, mock_redis):
        """check_pause should return False if no word"""
        mock_redis.get_word_buffer.return_value = WordBuffer(
            session_id="test",
            user_id="user1",
            letters=[]
        )
        
        result = commit_engine.check_pause("test")
        assert result is False
    
    def test_check_pause_recent_commit(self, commit_engine, mock_redis):
        """check_pause should return False if recent commit"""
        now = datetime.now().timestamp()
        
        mock_redis.get_word_buffer.return_value = WordBuffer(
            session_id="test",
            user_id="user1",
            letters=["A", "W"],
            last_commit_time=now - 0.3  # 300ms ago (< 500ms)
        )
        
        result = commit_engine.check_pause("test")
        assert result is False
    
    def test_check_pause_detects_pause(self, commit_engine, mock_redis):
        """check_pause should return True after pause threshold"""
        now = datetime.now().timestamp()
        
        mock_redis.get_word_buffer.return_value = WordBuffer(
            session_id="test",
            user_id="user1",
            letters=["A", "W", "S"],
            last_commit_time=now - 0.6  # 600ms ago (> 500ms)
        )
        
        result = commit_engine.check_pause("test")
        assert result is True

