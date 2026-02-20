"""Configuration for Word Resolver Service"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Service
    service_name: str = "word-resolver-service"
    log_level: str = "INFO"
    
    # AWS
    aws_region: str = "us-east-1"
    letters_stream_name: str = "asl-letters-stream"
    outbound_lambda_name: str = os.getenv("OUTBOUND_LAMBDA_NAME", "asl-outbound-lambda")
    
    # Redis (ElastiCache)
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = 0
    redis_decode_responses: bool = True
    
    # MongoDB Atlas
    mongodb_url: str = os.getenv("MONGODB_URL", "")
    mongodb_db: str = "Glossa"
    mongodb_collection: str = "lexicon"
    
    # Sliding Window Configuration
    window_duration_ms: int = 300  # 300ms sliding window (increased from 200ms)
    stability_duration_ms: int = 200  # 200ms stability requirement (increased from 135ms)
    
    # Word Finalization
    pause_duration_ms: int = 2000  # 2s pause triggers word finalization
    max_consecutive_same: int = 1  # Maximum consecutive same letters (e.g., AA is ok, AAA is not)
    
    # Commit Rules
    min_confidence: float = 0.3  # Minimum confidence to consider
    
    # MongoDB Atlas Search
    atlas_search_index: str = "default"
    fuzzy_max_edits: int = 2
    fuzzy_prefix_length: int = 0
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

