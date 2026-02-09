"""
Test MongoDB Atlas Text Search with Real Data from Pipeline
Tests if wrongly predicted words can be recognized via fuzzy search
"""

import os
from pymongo import MongoClient

# Load environment variables
def load_env():
    env_file = '.env'
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if 'MONGODB_URL' in line and '=' in line:
                    return line.split('=', 1)[1].strip()
    return None

# Initialize MongoDB connection
MONGODB_URL = load_env()
if not MONGODB_URL:
    print("Error: MONGODB_URL not found in .env")
    exit(1)

client = MongoClient(
    MONGODB_URL,
    tls=True,
    tlsAllowInvalidCertificates=False,
    serverSelectionTimeoutMS=5000
)
db = client['Glossa']
collection = db['lexicon']

print("=" * 80)
print("MongoDB Atlas Search Test - Real Pipeline Data")
print("=" * 80)

# Check what data we have
print("\n1. Checking ingested data from pipeline...")
user_id = 'thongnguyen'
count = collection.count_documents({'user_id': user_id})
print(f"✓ Found {count} surface terms for user '{user_id}'")

# Get some sample terms
print("\n2. Sample surface terms and aliases:")
sample_docs = list(collection.find({'user_id': user_id}).limit(10))
for i, doc in enumerate(sample_docs, 1):
    surface = doc.get('surface', 'N/A')
    aliases = doc.get('aliases', [])
    print(f"   {i}. {surface:20} → {len(aliases)} aliases: {aliases[:5]}")

print("\n" + "=" * 80)
print("3. Testing Atlas Fuzzy Search on Real Aliases")
print("=" * 80)

# Get one term with aliases to test
test_doc = collection.find_one({'user_id': user_id, 'alias_count': {'$gte': 5}})
if not test_doc:
    print("No terms with aliases found!")
    exit(1)

surface = test_doc['surface']
aliases = test_doc['aliases']
print(f"\nTest Surface Term: {surface}")
print(f"Generated Aliases: {aliases[:10]}")

# Create test queries by simulating common ASL confusions
print("\n" + "-" * 80)
print("Testing Fuzzy Search (simulating ASL fingerspelling errors)")
print("-" * 80)

# Pick a few aliases to test
test_queries = []
if len(aliases) >= 3:
    # Test exact alias match
    test_queries.append((aliases[0], surface, "Exact alias match"))
    # Test with 1-character error
    if len(aliases[1]) > 2:
        typo = aliases[1][:-1] + ('X' if aliases[1][-1] != 'X' else 'Y')
        test_queries.append((typo, surface, "Alias with 1-char typo"))
    # Test another alias
    test_queries.append((aliases[2] if len(aliases) > 2 else aliases[0], surface, "Another alias"))

# Add some generic test cases
test_queries.extend([
    ("AWS", "AWS", "Common term - exact"),
    ("AW6", "AWS", "W→6 confusion"),
    ("AWX", "AWS", "Completely different"),
    ("A", "AWS", "Commit too soon"),
    ("AWWS", "AWS", "W→WW double character"),
    ("AW6WS", "AWS", "W→6W mixed"),
    ("AWWST", "AWS", "Too many wrong characters"),
    ("A6S", "AWS", "W→6 confusion alt"),
    ("AAWW", "AWS", "W→WW double character"),
    ("AGENT", "AGENT", "Common term - exact"),
    ("EGENT", "AGENT", "A→E confusion"),
    ("EKGENT", "AGENT", "Completely different added"),
    ("PYTHON", "PYTHON", "Common term (may not exist)"),
    ("PYT7ON", "PYTHON", "H→7 confusion (may not exist)"),
    ("MACHINE", "MACHINE", "Term not in document (no results expected)"),
])

for query, expected, description in test_queries:
    print(f"\nQuery: '{query}' (expecting: '{expected}')")
    print(f"  Description: {description}")
    search_strategy = "autocomplete" if len(query) <= 3 else "fuzzy"
    print(f"  Strategy: {search_strategy}")
    
    try:
        # MongoDB Atlas Search with autocomplete + fuzzy fallback
        # Use autocomplete for short queries (prefix matching) and fuzzy for longer/complete queries
        use_autocomplete = len(query) <= 3  # Short queries benefit from autocomplete
        
        if use_autocomplete:
            # Autocomplete prefix search: good for incomplete words like "A" → "AWS", "API"
            # Uses edgeGram tokenization for left-to-right matching
            pipeline = [
                {
                    '$search': {
                        'index': 'default',
                        'compound': {
                            'should': [
                                {
                                    'autocomplete': {
                                        'query': query.lower(),
                                        'path': 'aliases',
                                        'fuzzy': {
                                            'maxEdits': 1,
                                            'prefixLength': 0
                                        }
                                    }
                                },
                                {
                                    'autocomplete': {
                                        'query': query.lower(),
                                        'path': 'surface',
                                        'fuzzy': {
                                            'maxEdits': 1,
                                            'prefixLength': 0
                                        }
                                    }
                                }
                            ],
                            'filter': [
                                {
                                    'equals': {
                                        'path': 'user_id',
                                        'value': user_id
                                    }
                                }
                            ]
                        }
                    }
                },
                {
                    '$project': {
                        'surface': 1,
                        'aliases': 1,
                        'confidence_scores': 1,
                        'score': {'$meta': 'searchScore'}
                    }
                },
                {
                    '$limit': 20
                }
            ]
        else:
            # Fuzzy text search: good for complete words with typos like "AWX" → "AWS"
            pipeline = [
                {
                    '$search': {
                        'index': 'default',
                        'compound': {
                            'must': [
                                {
                                    'text': {
                                        'query': query.lower(),
                                        'path': ['aliases', 'surface'],
                                        'fuzzy': {'maxEdits': 2, 'prefixLength': 0}
                                    }
                                }
                            ],
                            'filter': [
                                {
                                    'equals': {
                                        'path': 'user_id',
                                        'value': user_id
                                    }
                                }
                            ]
                        }
                    }
                },
                {
                    '$project': {
                        'surface': 1,
                        'aliases': 1,
                        'confidence_scores': 1,
                        'score': {'$meta': 'searchScore'}
                    }
                },
                {
                    '$limit': 20
                }
            ]
        
        results = list(collection.aggregate(pipeline))
        
        if results:
            print(f"  ✅ Found {len(results)} result(s):")
            for i, result in enumerate(results, 1):
                result_surface = result.get('surface')
                atlas_score = result.get('score', 0)
                match_status = "✓" if result_surface == expected else "✗"
                
                # Get confidence score for the matched alias (client-side re-ranking)
                confidence_scores = result.get('confidence_scores', {})
                result_aliases = result.get('aliases', [])
                
                # Find which alias matched best and its confidence
                # Use fuzzy matching - find alias that starts with query or has low edit distance
                matched_alias = None
                alias_confidence = 0.0
                query_upper = query.upper()
                
                def simple_edit_distance(s1, s2):
                    """Simple Levenshtein distance for alias matching"""
                    if len(s1) > len(s2):
                        s1, s2 = s2, s1
                    distances = range(len(s1) + 1)
                    for i2, c2 in enumerate(s2):
                        distances_ = [i2+1]
                        for i1, c1 in enumerate(s1):
                            if c1 == c2:
                                distances_.append(distances[i1])
                            else:
                                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
                        distances = distances_
                    return distances[-1]
                
                # Find best matching alias
                best_distance = float('inf')
                for alias in result_aliases:
                    alias_upper = alias.upper().replace(' ', '').replace('-', '')
                    query_clean = query_upper.replace(' ', '').replace('-', '')
                    
                    # Exact match
                    if alias_upper == query_clean:
                        matched_alias = alias
                        alias_confidence = confidence_scores.get(alias, 0.0)
                        break
                    
                    # Prefix match (for autocomplete)
                    if alias_upper.startswith(query_clean) or query_clean in alias_upper:
                        distance = abs(len(alias_upper) - len(query_clean))
                        if distance < best_distance:
                            best_distance = distance
                            matched_alias = alias
                            alias_confidence = confidence_scores.get(alias, 0.0)
                    
                    # Edit distance match (for fuzzy)
                    else:
                        distance = simple_edit_distance(alias_upper, query_clean)
                        if distance <= 2 and distance < best_distance:
                            best_distance = distance
                            matched_alias = alias
                            alias_confidence = confidence_scores.get(alias, 0.0)
                
                # Hybrid score: 70% Atlas search score + 30% alias confidence
                hybrid_score = (atlas_score * 0.7) + (alias_confidence * 0.3)
                
                print(f"    {i}. {result_surface:20} (atlas: {atlas_score:.3f}, conf: {alias_confidence:.3f}, hybrid: {hybrid_score:.3f}) [{match_status}]")
                
                # Show matching aliases with their confidence (only for top result)
                if i == 1:
                    matching = []
                    for a in result_aliases[:5]:
                        if query.upper() in a or query.lower() in a.lower():
                            conf = confidence_scores.get(a, 0.0)
                            matching.append(f"{a}({conf:.2f})")
                    if matching:
                        print(f"       Matched via: {', '.join(matching)}")
                
                # Only show top 3 results for brevity
                if i >= 3:
                    if len(results) > 3:
                        print(f"    ... and {len(results) - 3} more results")
                    break
        else:
            print("  ❌ NO RESULTS FOUND")
            # Distinguish between no results due to index vs. term not in document
            if "may not exist" in description or "no results expected" in description:
                print("     → Term not in document (expected)")
            else:
                print("     → Atlas Search Index may not be configured, OR term doesn't exist in lexicon")
    
    except Exception as e:
        error_msg = str(e)
        if 'index not found' in error_msg.lower() or 'text index' in error_msg.lower():
            print(f"  ⚠️  SEARCH INDEX NOT FOUND")
            break
        else:
            print(f"  ❌ Error: {error_msg}")


client.close()

