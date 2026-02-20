"""Data models for Word Resolver Service"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class LetterPrediction(BaseModel):
    """Letter prediction from the letter-model-service"""
    session_id: str
    connection_id: str
    timestamp: str
    event_type: str  # 'prediction' or 'skip'
    prediction: Optional[str] = None
    confidence: Optional[float] = None
    handedness: Optional[str] = None
    multi_hand: bool = False
    processing_time_ms: float = 0.0
    skip_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LetterEntry(BaseModel):
    """Single letter entry in the sliding window"""
    char: str
    confidence: float
    timestamp: float  # Unix timestamp in seconds
    
    @property
    def age_ms(self) -> float:
        """Age of this entry in milliseconds"""
        return (datetime.now().timestamp() - self.timestamp) * 1000


class CommitCandidate(BaseModel):
    """Candidate letter for commit"""
    char: str
    aggregate_confidence: float
    first_seen: float  # Unix timestamp
    last_seen: float
    count: int
    
    @property
    def stability_duration_ms(self) -> float:
        """How long this character has been dominant (ms)"""
        return (self.last_seen - self.first_seen) * 1000


class WordBuffer(BaseModel):
    """Word being constructed from committed letters"""
    session_id: str
    user_id: str
    letters: List[str] = Field(default_factory=list)
    last_commit_time: Optional[float] = None
    created_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    
    @property
    def current_word(self) -> str:
        """Current word string"""
        return "".join(self.letters)
    
    @property
    def time_since_last_commit_ms(self) -> Optional[float]:
        """Time since last letter commit (ms)"""
        if self.last_commit_time is None:
            return None
        return (datetime.now().timestamp() - self.last_commit_time) * 1000


class SearchResult(BaseModel):
    """Single search result from MongoDB Atlas"""
    surface: str
    atlas_score: float
    alias_confidence: float  # Confidence from matched alias
    hybrid_score: float  # 70% atlas + 30% alias confidence
    matched_via: Optional[str] = None


class ResolvedWord(BaseModel):
    """Finalized and resolved word with top 5 results ranked by hybrid score"""
    session_id: str
    user_id: str
    raw_word: str  # Raw letters committed
    all_results: List[SearchResult] = Field(default_factory=list)  # Top 5 results with hybrid scores
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    search_method: str = "fuzzy"  # 'fuzzy' or 'skip_event'

