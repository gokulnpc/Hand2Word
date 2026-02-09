"""
Local test script for KB Aliases Lambda
Tests the alias generation logic without deploying to AWS
"""

import json
import os
import sys

# Load environment variables from .env file
def load_env_file():
    """Load environment variables from .env file if it exists."""
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value

load_env_file()

# Set environment variables for testing (override if needed)
os.environ.setdefault('KB_JOBS_TABLE', 'test-kb-jobs')
os.environ.setdefault('KB_RAW_BUCKET', 'test-kb-raw')
os.environ.setdefault('KB_ALIASES_BUCKET', 'test-kb-aliases')
os.environ.setdefault('ENVIRONMENT', 'local-test')
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')

# Import the lambda function
import lambda_function

def test_alias_validation():
    """Test the alias validation logic."""
    print("\n=== Testing Alias Validation ===\n")
    
    test_cases = [
        # Digit-letter swaps
        ("AWS", "AW6", True),  # W↔6 confusion
        ("AWS", "AW6T", True),  # W↔6 confusion (with extra char)
        ("GOOD", "G001", False), # 3 distance
        ("FIVE", "FI2E", True),  # V↔2 confusion
        ("DAN", "1AN", True),  # D↔1 confusion
        ("WOW", "6O6", True),  # W↔6 confusion (both W's)
        
        # Compact-fist group (E, S, N, T, M, A)
        ("TEST", "TAST", True),  # E↔A confusion
        ("BEST", "BAST", True),  # E↔A confusion
        ("SENT", "SEMT", True),  # N↔M confusion
        ("NEST", "MEST", True),  # N↔M confusion
        ("TEST", "TEMT", True),  # S↔M confusion via E
        ("SEAT", "SNAT", True),  # E↔N confusion
        
        # Orientation/mirror group (H, 7, V, U)
        ("HELLO", "UELLO", True),  # H↔U confusion
        ("HELLO", "7ELLO", True),  # H↔7 confusion
        ("HAVE", "UA7E", True),  # H↔U, V↔7 confusion
        ("VIEW", "7IEW", True),  # V↔7 confusion
        
        # Circle/thumb-contact
        ("CODE", "C0DE", True),  # O↔0 confusion
        ("COOL", "C00L", True),  # O↔0 confusion (both O's)
        ("CODE", "CUDE", True),  # O↔U confusion (if within known)
        ("DOT", "1OT", True),  # D↔1 confusion
        
        # Dynamic/motion group
        ("JAZZ", "JA11", True),  # Z↔1 confusion
        ("JAM", "IAM", True),  # J↔I confusion
        
        # Structural edits
        ("AWS", "A W S", True),  # Spaced variant
        ("AWS", "A-W-S", True),  # Hyphenated variant
        ("WWW", "WW", True),  # Repetition/deletion
        
        # Invalid cases
        ("AWS", "COMPLETELY_DIFFERENT", False),  # Too different
        ("AWS", "A", False),  # Too short after normalization
        ("AWS", "AWSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS", False),  # Too long
        ("AWS", "AWS@123", False),  # Invalid characters
        ("TEST", "ZZZZ", False),  # No valid confusions
    ]
    
    passed = 0
    failed = 0
    for surface, alias, expected_valid in test_cases:
        is_valid, score = lambda_function.validate_alias(surface, alias)
        status = "✓" if is_valid == expected_valid else "✗"
        if is_valid == expected_valid:
            passed += 1
        else:
            failed += 1
        print(f"{status} Surface: {surface:15} Alias: {alias:30} Valid: {is_valid:5} Score: {score:.3f}")
    
    print(f"\nValidation Tests: {passed} passed, {failed} failed")

def test_confusion_probability():
    """Test confusion probability calculations."""
    print("\n=== Testing Confusion Probabilities ===\n")
    
    test_pairs = [
        ### Compact-fist group (E, S, N, T, M, A)
        ('E', 'S'),
        ('E', 'T'),
        ('E', 'A'),
        ('E', 'N'),
        ('E', 'M'),
        ('M', 'N'),
        ('M', 'T'),
        ('S', 'N'),
        ('S', 'T'),
        ('T', 'A'),
        
        ### Circle/thumb-contact group
        ('C', '0'),
        ('C', 'O'),
        ('O', '0'),

        ### Dynamic/motion group
        ('J', 'I'),
        ('Z', '1'),
        ('J', 'Z'),

        ### Orientation/mirror group (H, 7, V, U)
        ('H', 'U'),
        ('H', 'V'),
        ('H', '7'),
        ('U', 'V'),
        ('7', 'V'),
        ('7', 'U'),
        
        ### R-U-V group
        ('R', 'U'),
        ('R', 'V'),
        ('V', '2'),
        
        ### Digit-letter swaps
        ('W', '6'),  # High confusion
        ('W', '3'),
        ('D', '1'),
        ('F', '9'),
        
    ]
    
    print("Matrix Prob | Known Conf | Pair")
    print("-" * 45)
    for char1, char2 in test_pairs:
        prob = lambda_function.get_confusion_prob(char1, char2)
        is_known = lambda_function.is_known_confusion(char1, char2)
        status = "✓" if is_known else " "
        print(f"  {prob:.4f}    |     {status}      | {char1} ↔ {char2}")

def test_edit_distance():
    """Test edit distance calculations."""
    print("\n=== Testing Edit Distance ===\n")
    
    test_cases = [
        ("AWS", "AWS", 0),
        ("AWS", "AW6", 1),
        ("AWS", "A W S", 2),  # Spaces count
        ("HELLO", "HELO", 1),
        ("TEST", "TAST", 1),
    ]
    
    for s1, s2, expected in test_cases:
        dist = lambda_function.levenshtein_distance(s1, s2)
        status = "✓" if dist == expected else "✗"
        print(f"{status} '{s1}' → '{s2}': distance = {dist} (expected {expected})")

def test_placeholder_aliases():
    """Test placeholder alias generation."""
    print("\n=== Testing Placeholder Alias Generation ===\n")
    
    test_terms = ["AWS", "HELLO", "TEST", "BOB", "WORLD"]
    
    aliases = lambda_function.generate_placeholder_aliases(test_terms)
    
    for term, alias_list in aliases.items():
        print(f"\n{term}:")
        for alias_obj in alias_list:
            print(f"  - {alias_obj['alias']:20} (confidence: {alias_obj['confidence']})")

def test_llm_alias_generation():
    """Test LLM-based alias generation (requires AWS credentials and Bedrock access)."""
    print("\n=== Testing LLM Alias Generation ===\n")
    print("Note: This requires AWS credentials and Bedrock model access")
    
    test_terms = ["AWS", "HELLO", "TEST"]
    
    try:
        aliases = lambda_function.generate_aliases_with_llm(test_terms, batch_size=3)
        
        print(f"\nGenerated aliases for {len(aliases)} terms:\n")
        for term, alias_list in aliases.items():
            print(f"\n{term} ({len(alias_list)} aliases):")
            for alias_obj in alias_list[:5]:  # Show top 5
                print(f"  - {alias_obj['alias']:20} (confidence: {alias_obj['confidence']:.3f})")
    except Exception as e:
        print(f"✗ Error: {e}")
        print("Falling back to placeholder mode...")
        test_placeholder_aliases()

def test_mongodb_connection():
    """Test MongoDB connection."""
    print("\n=== Testing MongoDB Connection ===\n")
    
    try:
        db = lambda_function.get_mongo_db()
        if db is None:
            print("⚠️  MongoDB URL not configured in environment")
            return False
        
        # Test connection by pinging
        db.command('ping')
        print(f"✓ Connected to MongoDB database: {db.name}")
        
        # Check if lexicon collection exists
        collections = db.list_collection_names()
        if 'lexicon' in collections:
            count = db['lexicon'].count_documents({})
            print(f"✓ Lexicon collection exists with {count} documents")
        else:
            print("⚠️  Lexicon collection does not exist yet")
        
        return True
        
    except Exception as e:
        print(f"✗ MongoDB connection failed: {e}")
        return False

def test_full_pipeline():
    """Test the full pipeline with a mock event."""
    print("\n=== Testing Full Pipeline (Mock Event) ===\n")
    
    # Create a mock SQS event
    mock_event = {
        "Records": [
            {
                "messageId": "test-123",
                "body": json.dumps({
                    "Type": "Notification",
                    "Message": json.dumps({
                        "job_id": "test-job-123",
                        "user_id": "testuser",
                        "terms_s3_key": "testuser/test_terms.json",
                        "term_count": 5
                    })
                })
            }
        ]
    }
    
    # Note: This will fail without actual AWS resources
    # Use this test after setting up test S3 buckets
    print("Mock event created. To test fully, you need:")
    print("1. AWS credentials configured")
    print("2. Test S3 buckets created")
    print("3. Sample terms JSON uploaded to S3")
    print("\nMock event structure:")
    print(json.dumps(mock_event, indent=2))

def main():
    """Run all tests."""
    import sys
    
    print("=" * 80)
    print("KB Aliases Lambda - Local Testing")
    print("=" * 80)
    
    # Check if --with-llm flag is provided
    test_llm = '--with-llm' in sys.argv
    
    # Run individual tests
    test_alias_validation()
    test_confusion_probability()
    test_edit_distance()
    
    # Test MongoDB connection
    test_mongodb_connection()
    
    if not test_llm:
        test_placeholder_aliases()
    
    # Show mock pipeline structure
    test_full_pipeline()
    
    # Run LLM test if requested
    if test_llm:
        print("\n" + "=" * 80)
        print("Running LLM Alias Generation Test")
        print("=" * 80)
        test_llm_alias_generation()
    
    print("\n" + "=" * 80)
    print("✓ Basic validation tests complete!")
    print("=" * 80)
    
    if not test_llm:
        print("\nTo test LLM alias generation:")
        print("1. Configure AWS credentials: export AWS_PROFILE=AdministratorAccess-837563944845")
        print("2. Run: uv run python test_local.py --with-llm")
        print("=" * 80)

if __name__ == "__main__":
    main()

