"""
KB Aliases LLM Lambda Function
Triggered by SQS messages when cleaned terms are ready.
- Retrieves cleaned terms from S3
- Calls LLM (via Strand Agent) to generate aliases for ASL fingerspelling confusions
- Validates and scores aliases using confusion matrix
- Stores aliases back to S3
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
import boto3
from strands import Agent
from strands.models import BedrockModel
from pymongo import MongoClient, UpdateOne

# AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Environment variables
KB_JOBS_TABLE = os.environ['KB_JOBS_TABLE']
KB_RAW_BUCKET = os.environ['KB_RAW_BUCKET']
KB_ALIASES_BUCKET = os.environ['KB_ALIASES_BUCKET']
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
MONGODB_URL = os.environ.get('MONGODB_URL')

# DynamoDB table
kb_jobs_table = dynamodb.Table(KB_JOBS_TABLE)

# MongoDB client (lazy initialization)
_mongo_client = None
_mongo_db = None

def get_mongo_db():
    """Get or create MongoDB client and database."""
    global _mongo_client, _mongo_db
    if _mongo_db is None and MONGODB_URL:
        # Configure MongoDB client with TLS settings
        _mongo_client = MongoClient(
            MONGODB_URL,
            tls=True,
            tlsAllowInvalidCertificates=False,
            serverSelectionTimeoutMS=5000
        )
        _mongo_db = _mongo_client['Glossa']  # Database name
    return _mongo_db

# System prompt for LLM alias generation
SYSTEM_PROMPT = """
TASK
Generate spelling-level alias variants for ASL fingerspelling, using ONLY the confusion pairs listed below.

OUTPUT (JSON ONLY)
Return an UPPERCASE JSON array of objects. No prose, no markdown. Example:
[
  {"surface":"AWS","aliases":["AW6","A W S"]}
]
Constraints:
- surface: UPPERCASE, 2–40 chars
- aliases: array of UPPERCASE strings (2–40 chars), max 50 per surface, minimum 10 per surface
- Return valid JSON only

ALLOWED CONFUSIONS (ONLY THESE)

1) Digit ↔ Letter swaps
- W ↔ 6
- W ↔ 3
- V ↔ 2
- F ↔ 9
- D ↔ 1
- O ↔ 0

2) Compact-fist look-alikes (A / E / S / T / M / N)
- A ↔ E, A ↔ T    (NOT A ↔ S)
- E ↔ S, E ↔ T, E ↔ A, E ↔ N, E ↔ M
- T ↔ A, T ↔ E, T ↔ M   (NOT T ↔ S)
- S ↔ N, S ↔ T
- N ↔ M

3) Orientation / mirror / pointing-finger
- H ↔ U, H ↔ V, H ↔ 7
- R ↔ U, R ↔ V
- U ↔ V, U ↔ 7
- V ↔ 7, V ↔ 2

4) Circle or thumb-contact shapes
- C ↔ O, C ↔ 0
- D ↔ 1
- O ↔ 0

5) Dynamic / motion-dependent / similar shapes
- J ↔ Z
- J ↔ I
- Z ↔ 1

STRUCTURAL EDITS
- Allow minor repetition or deletion of one character (“WW” ↔ “W”).
- Allow spacing/hyphenation (“AWS” → “A W S”, “A-W-S”).
- Disallow any alias with edit distance > 2 from surface or length < 2.

RULES
- Apply substitutions anywhere (first/middle/last character).
- Do NOT modify any character unless it appears in the allowed lists above.
- Ignore "_" (pause); never emit it.
- Output JSON ONLY in uppercase; do not add explanations.
"""


# Initialize Bedrock model and agent globally for reuse across invocations
# This reduces cold start time and reuses connections
_agent = None

def get_agent():
    """Get or create the global agent instance."""
    global _agent
    if _agent is None:
        model = BedrockModel(
            model_id="us.anthropic.claude-3-5-sonnet-20240620-v1:0",
            temperature=0.2
        )
        _agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT
        )
    return _agent

# ASL Confusion Matrix (from data)
# This is used to VALIDATE the LLM-generated aliases and SCORE them
# The matrix tells us which character confusions actually occur in real ASL fingerspelling
# Indices: 0-9 = digits 0-9, 10-35 = letters A-Z, 36 = "_"
CONFUSION_MATRIX = [
    [434, 12, 1, 0, 1, 1, 0, 2, 0, 0, 2, 0, 9, 2, 2, 0, 0, 0, 0, 2, 0, 0, 0, 3, 8, 1, 0, 0, 0, 4, 0, 0, 0, 1, 1, 0, 20],
    [2, 681, 19, 0, 0, 0, 3, 2, 0, 0, 18, 2, 0, 48, 1, 0, 1, 0, 2, 0, 3, 0, 0, 7, 2, 1, 0, 1, 3, 10, 0, 0, 1, 7, 1, 0, 3],
    [5, 129, 542, 11, 0, 3, 11, 3, 2, 1, 6, 2, 1, 9, 2, 0, 1, 0, 1, 0, 25, 3, 0, 4, 2, 0, 0, 0, 7, 10, 8, 40, 0, 0, 1, 0, 1],
    [5, 20, 8, 1100, 3, 12, 0, 2, 2, 3, 3, 0, 1, 8, 0, 0, 0, 0, 0, 0, 7, 9, 0, 0, 0, 0, 1, 0, 0, 2, 0, 2, 0, 0, 0, 0, 5],
    [4, 1, 1, 2, 1272, 23, 0, 1, 0, 1, 0, 10, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 3],
    [1, 1, 0, 2, 19, 1862, 0, 1, 4, 2, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 2, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0],
    [7, 13, 24, 2, 7, 10, 680, 9, 8, 0, 7, 0, 5, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 3, 5, 44, 3, 1, 1, 2],
    [9, 10, 5, 2, 40, 7, 7, 1018, 9, 3, 12, 0, 7, 0, 0, 0, 0, 0, 8, 0, 1, 0, 0, 1, 3, 0, 0, 0, 0, 3, 0, 4, 0, 0, 0, 0, 6],
    [4, 3, 1, 2, 26, 13, 4, 25, 1049, 21, 2, 1, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 0, 1, 6, 0, 0, 0, 0, 4, 0, 0, 0, 0, 1, 1, 1],
    [5, 3, 1, 2, 3, 12, 1, 1, 1, 1138, 0, 1, 1, 0, 0, 22, 0, 0, 0, 0, 7, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
    [3, 19, 2, 3, 1, 2, 0, 5, 0, 2, 954, 7, 3, 3, 0, 0, 0, 0, 1, 0, 8, 0, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 2, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1772, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1685, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 16],
    [0, 21, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1746, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0],
    [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 63, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 0, 1, 0, 0, 5, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 31, 0, 10, 0, 0, 0, 1740, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1762, 3, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1770, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 3],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1700, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [4, 2, 0, 0, 1, 0, 0, 2, 0, 0, 1, 0, 0, 0, 0, 0, 2, 0, 4, 1360, 0, 0, 0, 1, 0, 1, 0, 0, 0, 3, 0, 0, 0, 1, 0, 2, 4],
    [0, 1, 2, 0, 0, 3, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1670, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1547, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 3, 0, 0, 0, 0, 0, 0, 0, 16, 3, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 2],
    [2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 0, 0, 1, 0, 5, 1509, 0, 0, 0, 0, 2, 1, 0, 0, 0, 0, 0, 0, 0],
    [79, 2, 0, 0, 0, 0, 0, 0, 2, 0, 1, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 36, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1760, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1761, 0, 1, 4, 0, 0, 0, 0, 0, 0, 0],
    [0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 852, 0, 0, 12, 5, 0, 0, 0, 0, 0],
    [9, 12, 0, 0, 0, 0, 0, 1, 0, 0, 4, 0, 6, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0, 12, 10, 0, 3, 0, 19, 6, 0, 0, 0, 0, 0, 0, 1],
    [4, 11, 0, 0, 0, 3, 0, 1, 1, 1, 10, 0, 0, 2, 1, 0, 0, 0, 0, 0, 1, 0, 0, 3, 3, 0, 1, 0, 0, 394, 0, 0, 0, 1, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1553, 0, 0, 0, 0, 0, 0],
    [0, 0, 14, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 12, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 2, 0, 0, 6, 852, 1, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 8, 0, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1738, 0, 0, 0, 0],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1765, 0, 0, 1],
    [3, 6, 3, 0, 0, 3, 0, 2, 3, 2, 15, 0, 0, 0, 3, 0, 0, 0, 0, 0, 3, 0, 0, 0, 1, 0, 0, 0, 0, 4, 0, 0, 0, 1, 97, 0, 5],
    [2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1499, 16],
    [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 881]
]

# Character mapping: index to character
def idx_to_char(idx: int) -> str:
    """Convert confusion matrix index to character."""
    if 0 <= idx <= 9:
        return str(idx)
    elif 10 <= idx <= 35:
        return chr(ord('A') + idx - 10)
    elif idx == 36:
        return '_'
    return '?'

def char_to_idx(char: str) -> int:
    """Convert character to confusion matrix index."""
    if char.isdigit():
        return int(char)
    elif char.isalpha():
        return ord(char.upper()) - ord('A') + 10
    elif char == '_':
        return 36
    return -1

# Known confusion pairs from empirical observations
# These may have low/zero confusion matrix probability but occur in practice
# Based on test_pairs in test_local.py - only include pairs that are actually confused
KNOWN_CONFUSION_PAIRS = {
    # Digit-Letter swaps (from test_pairs)
    ('W', '6'), ('6', 'W'),
    ('W', '3'), ('3', 'W'),
    ('V', '2'), ('2', 'V'),
    ('F', '9'), ('9', 'F'),
    ('D', '1'), ('1', 'D'),
    ('O', '0'), ('0', 'O'),
    
    # Compact-fist group (E, S, N, T, M, A) - excluding pairs model handles well
    ('A', 'T'), ('T', 'A'), ('A', 'E'), ('E', 'A'),
    ('E', 'S'), ('S', 'E'), ('E', 'T'), ('T', 'E'),
    ('E', 'N'), ('N', 'E'), ('E', 'M'), ('M', 'E'),
    ('T', 'M'), ('M', 'T'), ('S', 'N'), ('N', 'S'), ('S', 'T'), ('T', 'S'),
    ('N', 'M'), ('M', 'N'),
    
    # Orientation/mirror pairs (H, 7, V, U, R)
    ('H', 'U'), ('U', 'H'), ('H', 'V'), ('V', 'H'), ('H', '7'), ('7', 'H'),
    ('R', 'U'), ('U', 'R'), ('R', 'V'), ('V', 'R'),
    ('U', 'V'), ('V', 'U'), ('U', '7'), ('7', 'U'),
    ('V', '7'), ('7', 'V'),
    
    # Circle/thumb-contact
    ('C', 'O'), ('O', 'C'), ('C', '0'), ('0', 'C'),
    
    # Dynamic/motion
    ('J', 'Z'), ('Z', 'J'),
    ('J', 'I'), ('I', 'J'),
    ('Z', '1'), ('1', 'Z'),
}

def is_known_confusion(char1: str, char2: str) -> bool:
    """Check if a character pair is a known confusion."""
    return (char1.upper(), char2.upper()) in KNOWN_CONFUSION_PAIRS

def get_confusion_prob(char1: str, char2: str) -> float:
    """Get confusion probability between two characters from the matrix.
    Args:
        char1: The first character to compare.
        char2: The second character to compare.
    Returns:
        The confusion probability between the two characters. 
    """
    idx1 = char_to_idx(char1)
    idx2 = char_to_idx(char2)
    
    if idx1 == -1 or idx2 == -1:
        return 0.0
    
    # Get confusion count (symmetric)
    count = CONFUSION_MATRIX[idx1][idx2]
    total = sum(CONFUSION_MATRIX[idx1])
    
    return count / total if total > 0 else 0.0

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]

def confusion_weighted_edit_distance(surface: str, alias: str) -> float:
    """
    Calculate edit distance weighted by confusion probabilities.
    Returns a score where higher is better (inverted from distance).
    """
    # Remove spaces for comparison
    surface_clean = surface.replace(' ', '').replace('-', '')
    alias_clean = alias.replace(' ', '').replace('-', '')
    
    # Basic edit distance check
    edit_dist = levenshtein_distance(surface_clean, alias_clean)
    
    if edit_dist > 2:
        return 0.0  # Reject if edit distance too high
    
    # Calculate confusion-weighted score
    # For substitutions, use confusion probability
    score = 0.0
    matches = 0
    
    # Simple character-by-character comparison for aligned strings
    min_len = min(len(surface_clean), len(alias_clean))
    
    for i in range(min_len):
        if surface_clean[i] == alias_clean[i]:
            score += 1.0
            matches += 1
        else:
            # Use confusion probability for this substitution
            conf_prob = get_confusion_prob(surface_clean[i], alias_clean[i])
            
            # If this is a known confusion pair but has low/zero matrix probability,
            # give it a baseline score to account for empirical observations
            if conf_prob < 0.3 and is_known_confusion(surface_clean[i], alias_clean[i]):
                conf_prob = max(conf_prob, 0.4)  # Baseline for known confusions
            
            score += conf_prob
    
    # Normalize by surface length
    max_score = len(surface_clean)
    normalized_score = score / max_score if max_score > 0 else 0.0
    
    return normalized_score

def validate_alias(surface: str, alias: str) -> Tuple[bool, float]:
    """
    Validate an alias against the surface term.
    Returns (is_valid, confidence_score)
    """
    # Normalize
    alias = alias.upper().strip()
    surface = surface.upper().strip()
    
    # Basic validation
    if len(alias) < 2 or len(alias) > 40:
        return False, 0.0
    
    # Regex check: only A-Z, 0-9, spaces, hyphens
    if not re.match(r'^[A-Z0-9\-\s]{2,40}$', alias):
        return False, 0.0
    
    # Edit distance check
    clean_alias = alias.replace(' ', '').replace('-', '')
    clean_surface = surface.replace(' ', '').replace('-', '')
    
    if levenshtein_distance(clean_surface, clean_alias) > 2:
        return False, 0.0
    
    # Calculate confusion-weighted score
    score = confusion_weighted_edit_distance(surface, alias)
    
    # Keep only if score >= 0.5
    if score < 0.5:
        return False, score
    
    return True, score

def generate_aliases_with_llm(terms: List[str], batch_size: int = 100) -> Dict[str, List[Dict[str, Any]]]:
    """
    Generate aliases for terms using Strand Agent with Bedrock.
    Process terms in batches.
    """
    try:
        # Get global agent instance (reused across invocations)
        agent = get_agent()
        
        all_aliases = {}
        
        # Process in batches
        for i in range(0, len(terms), batch_size):
            batch = terms[i:i + batch_size]
            print(f"Processing batch {i // batch_size + 1}: {len(batch)} terms")
            
            # Create prompt with batch of terms
            prompt = f"Generate aliases for these terms:\n{json.dumps(batch)}"
            
            try:
                # Call LLM
                response = agent(prompt)
                print(f"LLM Response: {response}")
                
                # Parse response - extract JSON from response
                response_text = str(response)
                
                # Try to find JSON array in response
                json_start = response_text.find('[')
                json_end = response_text.rfind(']') + 1
                
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    llm_aliases = json.loads(json_str)
                    
                    # Validate and score each alias
                    for item in llm_aliases:
                        surface = item.get('surface', '').upper()
                        raw_aliases = item.get('aliases', [])
                        
                        if not surface or surface not in [t.upper() for t in batch]:
                            continue
                        
                        total_generated = len(raw_aliases)
                        validated_aliases = []
                        for alias in raw_aliases:
                            is_valid, score = validate_alias(surface, alias)
                            if is_valid:
                                validated_aliases.append({
                                    'alias': alias.upper(),
                                    'confidence': round(score, 3)
                                })
                        
                        # Sort by confidence descending
                        validated_aliases.sort(key=lambda x: x['confidence'], reverse=True)
                        
                        if validated_aliases:
                            all_aliases[surface] = validated_aliases
                            print(f"✓ {surface}: {len(validated_aliases)}/{total_generated} aliases validated")
                
            except json.JSONDecodeError as e:
                print(f"Failed to parse LLM response as JSON: {e}")
                print(f"Response was: {response_text[:500]}")
                continue
            except Exception as e:
                print(f"Error in batch processing: {e}")
                continue
        
        return all_aliases
        
    except ImportError:
        print("⚠️  Strands library not available, using placeholder mode")
        return generate_placeholder_aliases(terms)

def generate_placeholder_aliases(terms: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Generate simple placeholder aliases for testing without LLM."""
    aliases = {}
    for term in terms[:10]:  # Limit to 10 for placeholder
        term_upper = term.upper()
        placeholder_list = []
        
        # Add simple variants
        if len(term_upper) > 2:
            # Spaced version
            placeholder_list.append({
                'alias': ' '.join(term_upper),
                'confidence': 0.8
            })
        
        aliases[term_upper] = placeholder_list
    
    return aliases

def bulk_write_to_mongodb(aliases_data: Dict[str, List[Dict[str, Any]]], user_id: str, job_id: str) -> int:
    """
    Bulk write aliases to MongoDB Atlas with text search index.
    Returns number of documents written.
    
    Args:
        aliases_data: Dict mapping surface terms to their aliases
        user_id: User ID for the aliases
        job_id: Job ID for tracking
        
    Returns:
        Number of documents upserted
    """
    try:
        db = get_mongo_db()
        if db is None:
            print("⚠️  MongoDB URL not configured, skipping MongoDB write")
            return 0
        
        collection = db['lexicon']
        
        # Prepare bulk write operations
        operations = []
        for surface, alias_list in aliases_data.items():
            # Cap aliases to max 50 per surface
            capped_aliases = alias_list[:50]
            
            # Prepare document
            doc = {
                'surface': surface,
                'aliases': [a['alias'] for a in capped_aliases],
                'confidence_scores': {a['alias']: a['confidence'] for a in capped_aliases},
                'user_id': user_id,
                'job_id': job_id,
                'updated_at': datetime.now(timezone.utc),
                'alias_count': len(capped_aliases)
            }
            
            # Create upsert operation
            operations.append(
                UpdateOne(
                    {'surface': surface, 'user_id': user_id},  # Filter
                    {'$set': doc},  # Update
                    upsert=True  # Insert if not exists
                )
            )
        
        if operations:
            result = collection.bulk_write(operations, ordered=False)
            print(f"✓ MongoDB: {result.upserted_count} inserted, {result.modified_count} modified")
            return result.upserted_count + result.modified_count
        
        return 0
        
    except Exception as e:
        print(f"⚠️  MongoDB write error: {e}")
        import traceback
        traceback.print_exc()
        return 0

def lambda_handler(event, context):
    """
    Main Lambda handler for SQS messages from terms-ready SNS topic.
    
    Flow:
    1. Parse SQS message to get terms S3 key
    2. Download terms JSON from S3
    3. Call LLM (Strand Agent) to generate aliases in batches
    4. Validate and score aliases
    5. Upload aliases to S3
    """
    print(f"Event: {json.dumps(event)}")
    
    processed_count = 0
    failed_count = 0
    
    try:
        # Process each SQS message
        for record in event['Records']:
            try:
                # Parse SNS message from SQS
                sns_message = json.loads(record['body'])
                message_body = json.loads(sns_message['Message'])
                
                job_id = message_body['job_id']
                user_id = message_body['user_id']
                terms_s3_key = message_body['terms_s3_key']
                term_count = message_body['term_count']
                
                print(f"Processing terms for job {job_id}: {term_count} terms from s3://{KB_RAW_BUCKET}/{terms_s3_key}")
                
                # Download terms from S3
                terms_response = s3_client.get_object(
                    Bucket=KB_RAW_BUCKET,
                    Key=terms_s3_key
                )
                terms_data = json.loads(terms_response['Body'].read().decode('utf-8'))
                terms = terms_data['terms']
                
                print(f"Downloaded {len(terms)} terms from S3")
                
                # Generate aliases using LLM
                # Use smaller batch size to avoid hitting max_tokens limit
                aliases = generate_aliases_with_llm(terms, batch_size=50)
                
                # Prepare output data
                aliases_data = {
                    'job_id': job_id,
                    'user_id': user_id,
                    'terms_count': len(terms),
                    'aliases_count': len(aliases),
                    'processed_at': datetime.now(timezone.utc).isoformat(),
                    'aliases': aliases,
                    'status': 'COMPLETED'
                }
                
                # Upload aliases to S3
                base_name = os.path.splitext(os.path.basename(terms_s3_key))[0].replace('_terms', '')
                aliases_key = f"{user_id}/{base_name}_aliases.json"
                
                s3_client.put_object(
                    Bucket=KB_ALIASES_BUCKET,
                    Key=aliases_key,
                    Body=json.dumps(aliases_data, indent=2).encode('utf-8'),
                    ContentType='application/json'
                )
                
                print(f"✓ Uploaded aliases to s3://{KB_ALIASES_BUCKET}/{aliases_key}")
                print(f"✓ Generated aliases for {len(aliases)}/{len(terms)} terms")
                
                # Write to MongoDB Atlas
                mongo_docs_written = bulk_write_to_mongodb(aliases, user_id, job_id)
                if mongo_docs_written > 0:
                    print(f"✓ Wrote {mongo_docs_written} documents to MongoDB")
                
                processed_count += 1
                
            except Exception as e:
                print(f"Error processing message: {str(e)}")
                import traceback
                traceback.print_exc()
                failed_count += 1
                continue
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Batch processing complete',
                'processed': processed_count,
                'failed': failed_count,
                'environment': ENVIRONMENT
            })
        }
    
    except Exception as e:
        print(f"Fatal error processing batch: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
