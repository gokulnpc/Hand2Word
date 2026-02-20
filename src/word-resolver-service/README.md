# Word Resolver Service

**Kinesis Consumer** service that processes letter predictions from `asl-letters-stream`, applies commit rules, and resolves fingerspelled words using MongoDB Atlas fuzzy search.

## 📋 Overview

This service:
- **Consumes** letter predictions from `asl-letters-stream` (Kinesis)
- **Maintains** a sliding window buffer (200ms) in Redis for each session
- **Applies commit rules** to filter out flickering/unstable predictions
- **Resolves words** using MongoDB Atlas fuzzy search with alias matching
- **Handles pauses** to finalize words (400-600ms)

## 🏗️ Architecture

```
asl-letters-stream (Kinesis)
  ↓
[THIS SERVICE] ← Polls and processes
  ├─> ElastiCache Redis (sliding window state)
  ├─> MongoDB Atlas (fuzzy search)
  └─> [Future: Output stream/WebSocket]
```

### Data Flow

1. **Letter Ingestion**: Receive letter predictions from Kinesis
2. **Sliding Window**: Maintain 200ms window of recent predictions in Redis
3. **Commit Rules**:
   - Confidence-weighted voting (aggregate confidence per character)
   - Stability check (top character must be dominant for ≥120-150ms)
   - Deduplication (prevent same letter within 250ms)
4. **Word Finalization**: On pause (>500ms) or skip event
5. **Fuzzy Resolution**: Search MongoDB Atlas for best match

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region |
| `LETTERS_STREAM_NAME` | `asl-letters-stream` | Kinesis stream name |
| `REDIS_HOST` | `localhost` | Redis host (ElastiCache endpoint) |
| `REDIS_PORT` | `6379` | Redis port |
| `MONGODB_URL` | - | MongoDB Atlas connection string |
| `WINDOW_DURATION_MS` | `200` | Sliding window duration |
| `STABILITY_DURATION_MS` | `135` | Stability requirement (120-150ms) |
| `DEDUPE_THRESHOLD_MS` | `250` | Deduplication threshold |
| `PAUSE_DURATION_MS` | `500` | Pause detection (400-600ms) |
| `MIN_CONFIDENCE` | `0.3` | Minimum confidence to consider |

### Commit Rules Explained

#### 1. Confidence-Weighted Voting
```python
# Aggregate confidence for each character in the window
char_confidence = {}
for entry in window:
    if entry.confidence >= MIN_CONFIDENCE:
        char_confidence[entry.char] += entry.confidence

# Top character = highest aggregate confidence
top_char = max(char_confidence, key=char_confidence.get)
```

#### 2. Stability Check
```python
# Top character must stay dominant for ≥ STABILITY_MS
if (last_seen - first_seen) >= STABILITY_MS:
    commit(top_char)
```

#### 3. Deduplication
```python
# Prevent same letter if Δt < DEDUPE_MS
if top_char == last_committed_char and Δt < DEDUPE_MS:
    skip  # Likely jitter, not a new letter
```

### Word Finalization

Words are finalized when:
1. **Pause detected**: No letters committed for ≥ PAUSE_MS (500ms)
2. **Skip event**: Multi-hand or no-hand event from letter-model-service

## 🚀 Deployment

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Redis and MongoDB credentials

# Run locally (with local Redis)
python main.py
```

### Docker Build

Run Redis locally:
```bash
docker run -d --name redis-local -p 6379:6379 redis:7-alpine && echo "" && echo "✓ Redis running on localhost:6379"
```

```bash
docker build -t word-resolver-service:latest .
```

## 📊 Redis Data Structures

### Sliding Window (List/Deque)
```
Key: window:{session_id}
Type: List
Value: [LetterEntry, LetterEntry, ...]
TTL: 300s (5 minutes)
```

### Word Buffer (String)
```
Key: word:{session_id}
Type: String (JSON)
Value: {"session_id": "...", "letters": ["A", "W", "S"], ...}
TTL: 300s
```

### Last Commit (String)
```
Key: commit:{session_id}
Type: String (JSON)
Value: {"char": "A", "timestamp": 1234567890.123}
TTL: 60s (1 minute)
```

## 🔍 MongoDB Atlas Integration

### Search Pipeline

```python
{
  '$search': {
    'index': 'default',
    'compound': {
      'must': [
        {
          'text': {
            'query': 'aws',  # Raw fingerspelled word
            'path': ['aliases', 'surface'],
            'fuzzy': {'maxEdits': 2, 'prefixLength': 0}
          }
        }
      ],
      'filter': [
        {'equals': {'path': 'user_id', 'value': 'user123'}}
      ]
    }
  }
}
```

### Hybrid Scoring

```python
# 70% Atlas search score + 30% alias confidence
hybrid_score = (atlas_score * 0.7) + (alias_confidence * 0.3)
```

## 📈 Infrastructure

### ElastiCache Redis

- **Instance Type**: `cache.t3.micro` (dev)
- **Engine**: Redis 7.0
- **Purpose**: Session state management
- **Cost**: ~$12/month (on-demand)

Provisioned via Terraform:
```bash
cd iac/
terraform apply -target=aws_elasticache_cluster.redis
```

### IAM Permissions

The service requires:
- `kinesis:GetRecords`
- `kinesis:GetShardIterator`
- `kinesis:DescribeStream`

## 🧪 Testing

```bash
# Run unit tests
pytest tests/

# Test with local Redis
docker run -d -p 6379:6379 redis:7-alpine
python main.py
```

## 📝 Logging

Logs include:
- Letter commits: `✓ Committed 'A' → word: 'AWS' (session123)`
- Word finalization: `📤 Finalized word: 'AWS' → 'AWS' (session123)`
- Fuzzy search results: `✓ Resolved 'AWS' → 'AWS' (score: 5.23, conf: 0.85)`

## 🔮 Future Enhancements

1. **Output Stream**: Publish resolved words to Kinesis/SQS
2. **WebSocket Integration**: Send words back to client
3. **Advanced Commit Rules**: Contextual confidence adjustment
4. **Metrics**: CloudWatch metrics for commit rates, resolution accuracy
5. **KCL**: Use Kinesis Client Library for multi-shard processing

## 🐛 Troubleshooting

### Redis Connection Failed
```bash
# Check Redis endpoint
aws elasticache describe-cache-clusters --cache-cluster-id asl-word-resolver --show-cache-node-info

# Test connection
redis-cli -h <redis-endpoint> -p 6379 ping
```

### MongoDB Connection Failed
```bash
# Test connection string
mongosh "<MONGODB_URL>"
```

### No Records from Kinesis
```bash
# Check stream status
aws kinesis describe-stream --stream-name asl-letters-stream

# Check if letter-model-service is producing
aws logs tail /aws/lambda/letter-model-service --follow
```

