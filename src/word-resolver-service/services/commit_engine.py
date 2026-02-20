"""Commit Engine - Implements commit rules for letter recognition"""
import logging
from typing import Optional, List, Dict
from datetime import datetime
from collections import Counter
from config import settings
from models import LetterEntry, CommitCandidate, WordBuffer
from services.redis_manager import RedisManager

logger = logging.getLogger(__name__)


class CommitEngine:
    """
    Implements commit rules for letter recognition:
    1. Confidence-weighted voting over active window
    2. Stability check (top label dominant for ≥ STABILITY_MS)
    3. Max consecutive same letters (prevent more than 2 same letters in a row)
    """
    
    def __init__(self, redis_manager: RedisManager):
        self.redis = redis_manager
        self.window_duration_ms = settings.window_duration_ms
        self.stability_ms = settings.stability_duration_ms
        self.min_confidence = settings.min_confidence
        self.commit_min_confidence = 0.4  # Don't commit letters with confidence < 0.4
        self.max_consecutive_same = settings.max_consecutive_same
    
    def process_letter(
        self,
        session_id: str,
        user_id: str,
        char: str,
        confidence: float,
        timestamp: float
    ) -> Optional[WordBuffer]:
        """
        Process incoming letter prediction and potentially commit it.
        
        Returns:
            WordBuffer if letter was committed, None otherwise
        """
        # 1. Add to sliding window
        entry = LetterEntry(char=char, confidence=confidence, timestamp=timestamp)
        self.redis.push_letter(session_id, entry)
        
        # 2. Prune old entries (> window_duration_ms)
        now = datetime.now().timestamp()
        cutoff = now - (self.window_duration_ms / 1000.0)
        self.redis.prune_window(session_id, cutoff)
        
        # 3. Get active window
        window = self.redis.get_window(session_id)
        
        if not window:
            logger.debug(f"Empty window for {session_id}")
            return None
        
        # 4. Find top candidate via confidence-weighted voting
        candidate = self._find_top_candidate(window)
        
        if not candidate:
            logger.debug(f"No valid candidate for {session_id}")
            return None
        
        logger.debug(
            f"Top candidate: '{candidate.char}' "
            f"(conf: {candidate.aggregate_confidence:.2f}, "
            f"stability: {candidate.stability_duration_ms:.0f}ms)"
        )
        
        # # 5. Check minimum confidence threshold for commit
        avg_confidence = candidate.aggregate_confidence / candidate.count
        if avg_confidence < self.commit_min_confidence:
            logger.debug(
                f"Candidate '{candidate.char}' confidence too low "
                f"({avg_confidence:.2f} < {self.commit_min_confidence})"
            )
            return None
        
        # 6. Check stability requirement
        if candidate.stability_duration_ms < self.stability_ms:
            logger.debug(
                f"Candidate '{candidate.char}' not stable enough "
                f"({candidate.stability_duration_ms:.0f}ms < {self.stability_ms}ms)"
            )
            return None
        
        # 7. Check max consecutive same letters (max 2 in a row)
        buffer = self.redis.get_word_buffer(session_id, user_id)
        if len(buffer.letters) >= self.max_consecutive_same:
            # Check last N letters
            last_n = buffer.letters[-self.max_consecutive_same:]
            if all(letter == candidate.char for letter in last_n):
                logger.debug(
                    f"Skipping '{candidate.char}' - already have {self.max_consecutive_same} "
                    f"consecutive '{candidate.char}' letters"
                )
                return None
        
        # 8. COMMIT!
        buffer = self.redis.append_to_word(session_id, user_id, candidate.char)
        
        logger.info(
            f"✓ Committed '{candidate.char}' (conf={avg_confidence:.2f}, "
            f"stability={candidate.stability_duration_ms:.0f}ms) → word: "
            f"'{''.join(buffer.letters)}' ({session_id})"
        )
        
        return buffer
    
    def _find_top_candidate(self, window: List[LetterEntry]) -> Optional[CommitCandidate]:
        """
        Find top candidate using confidence-weighted voting.
        
        Strategy:
        - Filter entries with confidence >= min_confidence
        - Sum confidence scores for each character
        - Track first/last appearance for stability calculation
        """
        # Filter by confidence
        valid_entries = [e for e in window if e.confidence >= self.min_confidence]
        
        if not valid_entries:
            return None
        
        # Aggregate confidence per character
        char_data: Dict[str, Dict] = {}
        
        for entry in valid_entries:
            if entry.char not in char_data:
                char_data[entry.char] = {
                    'total_confidence': 0.0,
                    'count': 0,
                    'first_seen': entry.timestamp,
                    'last_seen': entry.timestamp
                }
            
            char_data[entry.char]['total_confidence'] += entry.confidence
            char_data[entry.char]['count'] += 1
            char_data[entry.char]['last_seen'] = max(
                char_data[entry.char]['last_seen'],
                entry.timestamp
            )
            char_data[entry.char]['first_seen'] = min(
                char_data[entry.char]['first_seen'],
                entry.timestamp
            )
        
        # Find character with highest aggregate confidence
        top_char = max(char_data.keys(), key=lambda c: char_data[c]['total_confidence'])
        data = char_data[top_char]
        
        return CommitCandidate(
            char=top_char,
            aggregate_confidence=data['total_confidence'],
            first_seen=data['first_seen'],
            last_seen=data['last_seen'],
            count=data['count']
        )
    
    def check_pause(self, session_id: str) -> bool:
        """
        Check if there's been a pause (no letters for > PAUSE_DURATION_MS).
        Returns True if word should be finalized.
        
        NOTE: This is event-driven - only checked when new events arrive.
        For session inactivity (no events for > τ_gap), the Kinesis consumer
        should periodically check active sessions or use a background timer.
        Current implementation: pause detection happens on next event arrival.
        """
        buffer = self.redis.get_word_buffer(session_id, "temp")
        
        if not buffer.letters:
            return False  # No word to finalize
        
        time_since_last = buffer.time_since_last_commit_ms
        
        if time_since_last is None:
            return False
        
        if time_since_last >= settings.pause_duration_ms:
            logger.info(
                f"⏸️  Pause detected for {session_id}: "
                f"{time_since_last:.0f}ms ≥ {settings.pause_duration_ms}ms"
            )
            return True
        
        return False

