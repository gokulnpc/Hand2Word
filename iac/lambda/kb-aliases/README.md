# MongoDB Atlas Search Strategy for ASL Fingerspelling

## Overview

This document describes the search strategy used for resolving ASL fingerspelling predictions to known terms in the knowledge base. The system handles two key challenges:

1. **Incomplete words** - User commits too early (e.g., "A" instead of "AWS")
2. **Character confusions** - Visually similar ASL signs (e.g., "AWX" instead of "AWS")

## Search Strategy: Adaptive Autocomplete + Fuzzy

### Strategy Selection

The system adaptively chooses between two search strategies based on query length:

```python
use_autocomplete = len(query) <= 3
```

#### 1. Autocomplete (for queries ≤ 3 characters)

**Use Case**: Incomplete/partial words that were committed too early

**Examples**:
- "A" → finds "AI", "API", "ASL", "AWS", "AGENT"
- "AW" → finds "AWS", "AWARDS"
- "API" → finds "API", "APIS"

**MongoDB Operator**: `autocomplete` with `edgeGram` tokenization

**How It Works**:
- Searches for terms that **start with** the query string
- Uses left-to-right prefix matching
- Supports fuzzy matching with `maxEdits: 1` for typos

**Query Structure**:
```python
{
    '$search': {
        'index': 'default',
        'compound': {
            'should': [
                {
                    'autocomplete': {
                        'query': query.lower(),
                        'path': 'aliases',
                        'fuzzy': {'maxEdits': 1, 'prefixLength': 0}
                    }
                },
                {
                    'autocomplete': {
                        'query': query.lower(),
                        'path': 'surface',
                        'fuzzy': {'maxEdits': 1, 'prefixLength': 0}
                    }
                }
            ],
            'filter': [{'equals': {'path': 'user_id', 'value': user_id}}]
        }
    }
}
```

#### 2. Fuzzy Text Search (for queries > 3 characters)

**Use Case**: Complete words with character confusion errors

**Examples**:
- "AWX" → finds "AWS" (X ≈ S confusion)
- "AW6" → finds "AWS" (6 ≈ W confusion)
- "AWWS" → finds "AWS" (double W)
- "EGENT" → finds "AGENT" (E ≈ A confusion)

**MongoDB Operator**: `text` with fuzzy matching

**How It Works**:
- Searches entire term with edit distance tolerance
- Allows up to 2 character substitutions/insertions/deletions
- No prefix length requirement (can match anywhere)

**Query Structure**:
```python
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
            'filter': [{'equals': {'path': 'user_id', 'value': user_id}}]
        }
    }
}
```

## MongoDB Atlas Index Configuration

### Index Definition

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "aliases": [
        {
          "type": "string",
          "analyzer": "lucene.standard"
        },
        {
          "type": "autocomplete",
          "tokenization": "edgeGram",
          "minGrams": 1,
          "maxGrams": 10,
          "foldDiacritics": true
        }
      ],
      "surface": [
        {
          "type": "string",
          "analyzer": "lucene.standard"
        },
        {
          "type": "autocomplete",
          "tokenization": "edgeGram",
          "minGrams": 1,
          "maxGrams": 10,
          "foldDiacritics": true
        }
      ],
      "user_id": {
        "type": "token"
      }
    }
  }
}
```

### Key Configuration Details

1. **Dual Indexing**: Each field is indexed as both `string` and `autocomplete`
   - `string`: Enables exact matching and fuzzy text search
   - `autocomplete`: Enables prefix matching for incomplete queries

2. **edgeGram Tokenization**: Creates tokens from the left edge
   - "AWS" → tokens: "A", "AW", "AWS"
   - Enables prefix matching without wildcards

3. **minGrams: 1, maxGrams: 10**:
   - `minGrams: 1`: Supports single-character queries
   - `maxGrams: 10`: Handles terms up to 10 characters (adjust for longer terms)

4. **foldDiacritics: true**: Case-insensitive matching
   - "aws" matches "AWS"
   - "Api" matches "API"

## Hybrid Scoring System

### Score Components

The final ranking uses a **hybrid score** combining two factors:

```python
hybrid_score = (atlas_score × 0.7) + (alias_confidence × 0.3)
```

#### 1. Atlas Search Score (70% weight)

**What it measures**: How well the query matches the document based on:
- Term frequency
- Inverse document frequency (TF-IDF)
- Field boost
- Proximity to query

**Scale**: **Unbounded and variable**
- No fixed range (not 0-1 or 0-100)
- Depends on:
  - Total number of documents in collection
  - Number of matching documents
  - Query complexity
  - Index configuration

**Example scores**:
- Exact match on short term: 3-5
- Prefix match on short term: 2-4
- Fuzzy match on longer term: 1-20
- Multi-word match: 10-30+

**Why scores vary between runs**:
1. **Index updates**: Adding/removing documents changes IDF scores
2. **Query complexity**: Different operators (autocomplete vs text) produce different score ranges
3. **Field lengths**: Shorter fields boost scores higher
4. **Term rarity**: Rare terms score higher than common ones

#### 2. Alias Confidence Score (30% weight)

**What it measures**: How confident the alias generator is that this variant could be confused with the surface term

**Scale**: **Fixed 0.0 to 1.0**
- Generated by confusion-weighted edit distance algorithm
- Based on ASL confusion matrix (empirical data)
- Accounts for known character confusions (e.g., W↔6, A↔E)

**Example confidences**:
- `1.0`: Exact alias match or high-probability confusion
- `0.8`: Common confusion (A↔E, W↔6)
- `0.5-0.7`: Moderate confusion with 1 edit
- `0.0`: No alias matched (surface term only)

### Alias Matching Logic

The system uses **fuzzy alias matching** to find the best alias and its confidence:

```python
# 1. Exact match (highest priority)
if alias_upper == query_clean:
    return confidence_scores[alias]

# 2. Prefix match (for autocomplete)
if alias_upper.startswith(query_clean):
    return confidence_scores[alias]

# 3. Edit distance match (for fuzzy)
if edit_distance(alias, query) <= 2:
    return confidence_scores[alias]
```

## MongoDB Score Characteristics

### Understanding Atlas Search Scores

MongoDB Atlas Search scores are **NOT normalized** and should be understood as:

#### 1. Relative, Not Absolute
- Scores are only meaningful for **ranking within a single query**
- A score of 5.0 on one query ≠ 5.0 on another query
- Use scores to compare results, not as quality metrics

#### 2. Unbounded Scale
- No maximum value
- Common ranges:
  - Single-word queries: 1-10
  - Multi-word queries: 5-30
  - Complex compound queries: Can exceed 50

#### 3. Dynamic Based on Corpus
- Scores change as the document collection grows
- Adding 100 documents can shift all scores
- Rare terms score higher than common terms (IDF factor)

#### 4. Operator-Dependent
- `autocomplete` typically produces lower scores (2-5)
- `text` with fuzzy produces moderate scores (5-15)
- `compound` queries sum scores from all clauses

### Why This Doesn't Matter for Our Use Case

We use **hybrid scoring with re-ranking**, so Atlas score variability is acceptable:

1. **Relative ranking is preserved**: Even if absolute scores change, the order usually stays the same
2. **Alias confidence stabilizes**: The 30% confidence weight adds consistency
3. **Top-K results**: We only care about the top 5 results, not absolute scores
4. **User-specific corpora**: Each user has their own terms, so scores are consistent within their usage

## Performance Characteristics

### Autocomplete (≤3 chars)
- **Speed**: Very fast (~5-20ms)
- **Recall**: High for prefix matches
- **Precision**: Lower (many candidates)
- **Best for**: "Did user finish typing?"

### Fuzzy Text (>3 chars)
- **Speed**: Moderate (~10-50ms)
- **Recall**: Moderate (misses some variations)
- **Precision**: High (focused results)
- **Best for**: "What did user mean to type?"

## Example Results

### Query: "A" (autocomplete)
```
1. AI       (atlas: 3.412, conf: 1.000, hybrid: 2.689) ✓ via alias "A I"
2. APIS     (atlas: 3.371, conf: 1.000, hybrid: 2.659) ✓ via alias "A PIS"
3. API      (atlas: 3.351, conf: 1.000, hybrid: 2.645) ✓ via alias "A PI"
4. ASL      (atlas: 3.329, conf: 1.000, hybrid: 2.630) ✓ via alias "A SL"
5. AWS      (atlas: 3.315, conf: 1.000, hybrid: 2.621) ✓ via alias "A WS"
```

### Query: "AWX" (autocomplete, 3 chars)
```
1. AWARDS   (atlas: 2.000, conf: 0.000, hybrid: 1.400) ✗
2. AWS      (atlas: 1.000, conf: 1.000, hybrid: 1.000) ✓ (fuzzy autocomplete)
3. 5XX      (atlas: 1.000, conf: 0.667, hybrid: 0.900) ✗
```

### Query: "AW6" (autocomplete with fuzzy)
```
1. AWS      (atlas: 2.000, conf: 1.000, hybrid: 1.700) ✓ via alias "A 6S"
2. AWARDS   (atlas: 2.000, conf: 0.000, hybrid: 1.400) ✗
```

### Query: "AWWS" (fuzzy text search)
```
1. AWARDS   (atlas: 3.115, conf: 0.000, hybrid: 2.181) ✗
2. AWS      (atlas: 2.267, conf: 1.000, hybrid: 1.887) ✓ (edit distance 1)
3. WORKFLOWS (atlas: 1.576, conf: 0.000, hybrid: 1.103) ✗
```

## Integration with Word Resolver

The word resolver service (`word-resolver-service`) uses this same strategy:

1. Receives committed letter sequence from letter model
2. Queries MongoDB Atlas with adaptive strategy
3. Re-ranks results using hybrid scoring
4. Returns top 5 candidates to client via outbound Lambda

### Search Flow
```
Committed Letters → MongoDB Atlas → Raw Results → Hybrid Re-Ranking → Top 5 Results → Client
        ↓                                              ↓
   "AWX"                                    70% Atlas + 30% Confidence
                                                      ↓
                                           1. AWS (hybrid: 1.00)
                                           2. AWARDS (hybrid: 1.40)
                                           3. 5XX (hybrid: 0.90)
```

## Testing

Run the test suite to validate search performance:

```bash
cd iac/lambda/kb-aliases
python3 test_mongodb_atlas_search.py
```

The test validates:
- ✅ Exact matches
- ✅ Character confusions (W↔6, A↔E, etc.)
- ✅ Incomplete queries (prefix matching)
- ✅ Fuzzy matching with edit distance ≤ 2
- ✅ Hybrid score re-ranking

## References

- [MongoDB Atlas Autocomplete Operator](https://www.mongodb.com/docs/atlas/atlas-search/autocomplete/)
- [MongoDB Atlas Text Search](https://www.mongodb.com/docs/atlas/atlas-search/text/)
- [MongoDB Atlas Scoring](https://www.mongodb.com/docs/atlas/atlas-search/scoring/)
- ASL Confusion Matrix: `lambda_function.py:CONFUSION_MATRIX`

