# Kinesis EFO Consumer Implementation

## 📋 Current Architecture

### Overview

The ASL Model Serving Service uses **AWS Kinesis Enhanced Fan-Out (EFO)** for consuming hand landmark data and producing ASL letter predictions. This document details the current implementation and recommended improvements.

### Data Flow

```
Client (WebSocket)
    ↓
API Gateway WebSocket API
    ↓
Ingress Lambda (asl-ingress-handler)
    ↓
asl-landmarks-stream (Kinesis)
    ↓ [EFO Consumer: letter-asl-service-{HOSTNAME}]
Model Serving Service (THIS SERVICE)
    ↓
asl-letters-stream (Kinesis)
    ↓ [Future]
Outbound Lambda
    ↓
API Gateway Management API
    ↓
Client (WebSocket)
```

### Kinesis Streams

| Stream Name | Shards | Purpose | Retention |
|------------|--------|---------|-----------|
| `asl-landmarks-stream` | 4 | Input: Hand landmarks from clients | 24 hours |
| `asl-letters-stream` | 4 | Output: ASL predictions to clients | 24 hours |

---

## 🚀 Current Implementation

### Enhanced Fan-Out (EFO) Consumer

**What is EFO?**
- **Push-based** delivery (vs. polling with `GetRecords`)
- **Dedicated throughput**: 2 MB/s per consumer per shard
- **Lower latency**: ~70ms average (vs. 200ms+ for polling)
- **Multiple consumers**: Each gets independent 2 MB/s throughput

**Current Setup:**
- Consumer Name: `letter-asl-service-{HOSTNAME}` (e.g., `letter-asl-service-local`, `letter-asl-service-c50ca64e73f7`)
- Starting Position: **`LATEST`** (real-time processing)
- All 4 shards subscribed concurrently
- Automatic re-subscription every ~5 minutes (EFO stream expiry)

### Implementation Details

#### 1. Consumer Registration & Management

```python
# Register EFO consumer on startup
consumer_name = f"letter-asl-service-{os.environ.get('HOSTNAME', 'local')}"
response = kinesis_client.register_stream_consumer(
    StreamARN=get_stream_arn(LANDMARKS_STREAM_NAME),
    ConsumerName=consumer_name
)

# Deregister on graceful shutdown (prevents "ResourceInUseException")
kinesis_client.deregister_stream_consumer(
    StreamARN=get_stream_arn(LANDMARKS_STREAM_NAME),
    ConsumerName=consumer_name
)
```

#### 2. Concurrent Shard Processing

Each of the 4 shards is processed in parallel using `asyncio.to_thread()` to avoid blocking:

```python
# Create async task for each shard
tasks = []
for shard in shards:
    task = asyncio.create_task(
        process_shard_with_efo(letter_asl_service, consumer_arn, shard['ShardId'])
    )
    tasks.append(task)

# Wait for all tasks
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**Why `asyncio.to_thread()`?**
- boto3's `subscribe_to_shard()` is **synchronous and blocking**
- Wrapping in thread pool allows all 4 shards to subscribe simultaneously
- Without this, shards would subscribe sequentially (blocking the event loop)

#### 3. Subscription Loop with Continuation

EFO subscriptions expire after **~5 minutes**, requiring automatic re-subscription:

```python
while not shutdown_flag:
    response = kinesis_client.subscribe_to_shard(
        ConsumerARN=consumer_arn,
        ShardId=shard_id,
        StartingPosition=starting_position  # LATEST or AFTER_SEQUENCE_NUMBER
    )
    
    continuation_sequence = None
    for event in response['EventStream']:
        if 'SubscribeToShardEvent' in event:
            shard_event = event['SubscribeToShardEvent']
            records = shard_event['Records']
            continuation_sequence = shard_event.get('ContinuationSequenceNumber')
            
            # Process records...
    
    # Re-subscribe using continuation sequence
    if continuation_sequence and not shutdown_flag:
        starting_position = {
            'Type': 'AFTER_SEQUENCE_NUMBER',  # Continue after last processed
            'SequenceNumber': continuation_sequence
        }
```

**Key Points:**
- ✅ Uses `AFTER_SEQUENCE_NUMBER` (not `AT_SEQUENCE_NUMBER`) to avoid re-processing
- ✅ Captures `ContinuationSequenceNumber` from every event
- ✅ Seamless re-subscription without data loss
- ✅ Infinite loop ensures service runs continuously

#### 4. Error Handling with Exponential Backoff

Implements industry-standard retry logic:

```python
retry_count = 0
max_retry_delay = 60  # seconds

# On error
retry_count += 1
base_delay = 2
exponential_delay = min(base_delay * (2 ** retry_count), max_retry_delay)
jitter = random.uniform(0, exponential_delay * 0.1)  # 10% jitter
retry_delay = exponential_delay + jitter
```

**Retry Schedule:**
- Retry 1: ~2.0s (2s + jitter)
- Retry 2: ~4.0s (4s + jitter)
- Retry 3: ~8.0s (8s + jitter)
- Retry 4: ~16.0s (16s + jitter)
- Retry 5: ~32.0s (32s + jitter)
- Retry 6+: ~60.0s (capped at max_retry_delay)

**Why Jitter?**
Prevents "thundering herd" when multiple consumers retry simultaneously.

---

## ✅ What's Working Well

### Strengths

1. **Low Latency**: EFO push-based delivery provides ~70ms latency
2. **Automatic Re-subscription**: Handles 5-minute EFO expiry gracefully
3. **Graceful Shutdown**: Properly deregisters consumers
4. **Concurrent Processing**: All 4 shards processed in parallel
5. **Correct Sequence Handling**: Uses `AFTER_SEQUENCE_NUMBER` to avoid duplicates
6. **Resilient Error Handling**: Exponential backoff with jitter
7. **Real-time Processing**: Starts from `LATEST` for live data

### Performance

- **Throughput**: ~500 records/second per shard (tested)
- **Processing Time**: 0.5-6ms per record (model inference)
- **End-to-End Latency**: <200ms (client → prediction)

---

## ⚠️ Current Limitations & Issues

### 1. ❌ No Checkpoint/State Management

**Problem:**
- If the service **crashes or restarts**, it starts from `LATEST`
- All **in-flight records are lost** (between crash and restart)
- No way to resume from last processed position

**Impact:**
- **Data loss during outages**
- **Missed predictions** for clients during restart window
- No disaster recovery capability

**Example Scenario:**
```
1. Service processing at sequence 12345
2. Service crashes
3. New records arrive: 12346, 12347, 12348
4. Service restarts → starts from LATEST (12349)
5. Records 12346-12348 are LOST forever ❌
```

### 2. ❌ No Monitoring of Lag

**Problem:**
- `MillisBehindLatest` is not tracked or logged
- No alerts when consumer falls behind
- Can't determine if scaling is needed

**What Should Be Monitored:**
```python
if 'SubscribeToShardEvent' in event:
    millis_behind = event['SubscribeToShardEvent'].get('MillisBehindLatest', 0)
    if millis_behind > 5000:  # 5 seconds behind
        logger.debug(f"Consumer lagging: {millis_behind}ms behind")
```

### 3. ⚠️ Single Consumer Instance

**Problem:**
- Only one instance of the service can run (per consumer name)
- No horizontal scaling within same shard
- EFO allows up to 20 consumers, but we use only 1

**Limitation:**
- Max throughput = 4 shards × 2 MB/s = **8 MB/s total**
- Can't scale beyond this without resharding

### 4. ⚠️ No Dead Letter Queue (DLQ)

**Problem:**
- Failed records are logged but not retried
- No mechanism to replay failed predictions
- Transient errors (e.g., model timeout) lose data permanently

### 5. ⚠️ Synchronous boto3 in Async Context

**Problem:**
- Using synchronous `boto3` with `asyncio.to_thread()` is a workaround
- More efficient to use `aioboto3` (async-native)
- Current approach creates new event loops per record (overhead)

```python
# Current (suboptimal)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(process_landmark_record(...))
loop.close()
```

---

## 🔮 Future Improvements

### Priority 1: Add Checkpointing (Critical)

**Goal:** Persist consumer progress to survive crashes

#### Option A: DynamoDB Checkpointing (KCL-style)

**Table Schema:**
```
asl-kinesis-checkpoints
├── shard_id (PK)          # "shardId-000000000000"
├── sequence_number        # "49667713619121671..."
├── checkpoint_timestamp   # ISO8601
├── consumer_name          # "letter-asl-service-local"
└── records_processed      # 12345
```

**Implementation:**
```python
# Save checkpoint every 10 records (batching for efficiency)
checkpoint_counter = 0
CHECKPOINT_INTERVAL = 10

for record in records:
    await process_landmark_record(record)
    checkpoint_counter += 1
    
    if checkpoint_counter >= CHECKPOINT_INTERVAL:
        checkpointer.save_checkpoint(
            shard_id=shard_id,
            sequence_number=record['SequenceNumber'],
            records_processed=total_processed
        )
        checkpoint_counter = 0

# On startup: resume from checkpoint
starting_position = checkpointer.get_starting_position(shard_id)
# Returns: {'Type': 'AFTER_SEQUENCE_NUMBER', 'SequenceNumber': '...'}
```

**Pros:**
- ✅ Survive crashes with minimal data loss
- ✅ Resume exactly where left off
- ✅ DynamoDB has low latency (~1-5ms writes)
- ✅ KCL-compatible pattern

**Cons:**
- ❌ Additional AWS costs ($0.25/GB + writes)
- ❌ Adds complexity
- ❌ Need to handle stale checkpoints

#### Option B: In-Memory with Periodic S3 Backup

**Implementation:**
```python
# Save to S3 every 1 minute
checkpoint_data = {
    'shards': {
        'shardId-000000000000': {
            'sequence_number': '...',
            'timestamp': datetime.utcnow().isoformat()
        }
    }
}

s3_client.put_object(
    Bucket='asl-checkpoints',
    Key=f'checkpoints/{consumer_name}/latest.json',
    Body=json.dumps(checkpoint_data)
)
```

**Pros:**
- ✅ Lower cost (S3 is cheap)
- ✅ Simpler implementation

**Cons:**
- ❌ Up to 1 minute of data loss on crash
- ❌ Slower recovery (S3 GET on startup)

**Recommendation:** Use **Option A (DynamoDB)** for production reliability.

---

### Priority 2: Add Lag Monitoring

**Implementation:**
```python
if 'SubscribeToShardEvent' in event:
    shard_event = event['SubscribeToShardEvent']
    millis_behind = shard_event.get('MillisBehindLatest', 0)
    
    # Log metrics
    logger.info(f"[{shard_id}] Lag: {millis_behind}ms")
    
    # Alert if lagging > 5 seconds
    if millis_behind > 5000:
        logger.debug(f"[{shard_id}] HIGH LAG: {millis_behind}ms behind")
        # TODO: Send CloudWatch metric
        cloudwatch.put_metric_data(
            Namespace='ASL/ModelServing',
            MetricData=[{
                'MetricName': 'ConsumerLag',
                'Value': millis_behind,
                'Unit': 'Milliseconds',
                'Dimensions': [{'Name': 'ShardId', 'Value': shard_id}]
            }]
        )
```

**Alerting:**
- Set CloudWatch alarm: `MillisBehindLatest > 5000ms` for 2 consecutive periods
- Trigger SNS notification or PagerDuty

---

### Priority 3: Add Dead Letter Queue (DLQ)

**Goal:** Capture and retry failed records

**Implementation:**
```python
try:
    result = await letter_asl_service.predict_from_landmarks(landmarks)
    put_prediction_to_kinesis(session_id, connection_id, result)
except Exception as e:
    logger.error(f"Failed to process record: {e}")
    
    # Write to DLQ (separate Kinesis stream or SQS)
    dlq_client.send_message(
        QueueUrl=DLQ_URL,
        MessageBody=json.dumps({
            'shard_id': shard_id,
            'sequence_number': record['SequenceNumber'],
            'data': record['Data'],
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat(),
            'retry_count': 0
        })
    )
```

**DLQ Processing:**
- Separate Lambda or background worker
- Retry with exponential backoff (3 attempts)
- Send to manual review queue if still failing

---

### Priority 4: Migrate to aioboto3

**Current Problem:**
```python
# Creates new event loop per record (expensive!)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(process_landmark_record(record))
loop.close()
```

**Better Approach:**
```python
# Use async-native AWS SDK
import aioboto3

session = aioboto3.Session()
async with session.client('kinesis') as kinesis_client:
    response = await kinesis_client.subscribe_to_shard(...)
    
    async for event in response['EventStream']:
        records = event['SubscribeToShardEvent']['Records']
        for record in records:
            await process_landmark_record(record)  # Native async
```

**Benefits:**
- ✅ True async I/O (no thread pool overhead)
- ✅ Better performance (fewer context switches)
- ✅ Cleaner code (no event loop juggling)

---

### Priority 5: Add Observability

#### Metrics to Track

**CloudWatch Metrics:**
```python
metrics = {
    'RecordsProcessed': records_processed,
    'ProcessingLatency': processing_time_ms,
    'PredictionConfidence': confidence,
    'ErrorRate': error_count / total_records,
    'MillisBehindLatest': millis_behind,
    'ActiveShards': len(active_shards)
}
```

**Distributed Tracing:**
- Enable OpenTelemetry (already scaffolded in `utils/tracer.py`)
- Trace end-to-end: Client → Lambda → Kinesis → Model → Kinesis
- Identify bottlenecks in processing pipeline

**Log Aggregation:**
- Stream logs to CloudWatch Logs
- Create log insights queries:
  ```sql
  fields @timestamp, session_id, prediction, confidence, processing_time_ms
  | filter prediction != "Unknown"
  | stats avg(confidence) by prediction
  ```

---

## 🏗️ Recommended Architecture (Future)

### With Checkpointing & DLQ

```
Client (WebSocket)
    ↓
API Gateway WebSocket API
    ↓
Ingress Lambda
    ↓
asl-landmarks-stream (Kinesis)
    ↓ [EFO Consumer with Checkpointing]
Model Serving Service
    ├─→ asl-letters-stream (Kinesis) [Success]
    └─→ asl-failed-predictions (SQS DLQ) [Failures]
            ↓
        DLQ Processor Lambda
            ├─→ Retry → asl-letters-stream
            └─→ Manual Review Queue (after 3 retries)
```

**Checkpoint Flow:**
```
DynamoDB Table: asl-kinesis-checkpoints
    ↕ (Read on startup / Write every 10 records)
Model Serving Service
```

---

## 📊 Cost Analysis

### Current Costs (4 shards, 1 consumer)

| Service | Usage | Monthly Cost |
|---------|-------|--------------|
| Kinesis EFO | 1 consumer × 4 shards × 720h | $36 ($0.0125/shard-hour) |
| Kinesis Data | Assume 100 GB/month | $4.25 ($0.0425/GB) |
| Kinesis PUT | Assume 10M records | $14 ($1.40/M) |
| **Total** | | **~$54/month** |

### With Checkpointing (DynamoDB)

| Service | Usage | Monthly Cost |
|---------|-------|--------------|
| DynamoDB Storage | 1 GB | $0.25 |
| DynamoDB Writes | 10M writes | $12.50 ($1.25/M) |
| DynamoDB Reads | 100K reads | $0.025 |
| **Total Added** | | **~$13/month** |

**Total with checkpointing: ~$67/month**

---

## 🎯 Implementation Roadmap

### Phase 1: Reliability (Weeks 1-2)
- ✅ **DONE**: Fix `AFTER_SEQUENCE_NUMBER` bug
- ✅ **DONE**: Add exponential backoff with jitter
- 🔲 **TODO**: Implement DynamoDB checkpointing
- 🔲 **TODO**: Add DLQ for failed records

### Phase 2: Observability (Week 3)
- 🔲 **TODO**: Add `MillisBehindLatest` monitoring
- 🔲 **TODO**: Create CloudWatch dashboard
- 🔲 **TODO**: Set up lag alerts (SNS)
- 🔲 **TODO**: Enable OpenTelemetry tracing

### Phase 3: Performance (Week 4)
- 🔲 **TODO**: Migrate to `aioboto3`
- 🔲 **TODO**: Optimize record batching
- 🔲 **TODO**: Profile hot paths
- 🔲 **TODO**: Load testing (1000 records/sec)

### Phase 4: Scaling (Future)
- 🔲 **TODO**: Horizontal scaling strategy
- 🔲 **TODO**: Auto-scaling based on lag
- 🔲 **TODO**: Multiple consumer groups (if needed)

---

## 📚 References

### AWS Documentation
- [Kinesis Enhanced Fan-Out](https://docs.aws.amazon.com/streams/latest/dev/enhanced-consumers.html)
- [SubscribeToShard API](https://docs.aws.amazon.com/kinesis/latest/APIReference/API_SubscribeToShard.html)
- [Kinesis Checkpointing Best Practices](https://docs.aws.amazon.com/streams/latest/dev/kinesis-record-processor-implementation-app-py.html)

### Code References
- Main implementation: `src/letter-model-sevice/main.py`
- Async processing: Lines 184-297 (`process_shard_with_efo_sync`)
- Consumer management: Lines 299-367 (`consume_and_process_efo`)
- Record processing: Lines 137-181 (`process_landmark_record`)

---

## 🤝 Contributing

When making changes to the Kinesis consumer:

1. **Test locally** with `test_local.sh`
2. **Verify graceful shutdown**: Consumer should deregister
3. **Check logs** for proper continuation sequence handling
4. **Monitor lag** after deployment
5. **Update this document** with any architectural changes

---

**Last Updated:** October 5, 2025  
**Version:** 1.0.0  
**Status:** ✅ Production-Ready (with noted limitations)

