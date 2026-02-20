# ASL Model Serving Service

**Kinesis Consumer/Producer** service that performs real-time ASL (American Sign Language) prediction on hand landmark data.

## 📋 Overview

This service:
- **Consumes** hand landmarks from `asl-landmarks-stream` (Kinesis) using **Enhanced Fan-Out (EFO)**
- **Processes** landmarks through a TensorFlow Lite model
- **Produces** predictions to `asl-letters-stream` (Kinesis)
- **No HTTP/REST endpoints** - pure event-driven architecture

> 📖 **For detailed implementation details and future roadmap**, see [Kinesis Implementation Guide](../Kinesis_implementation.md)

## 🏗️ Architecture

```
Client (app.py)
  ↓
API Gateway WebSocket
  ↓
Ingress Lambda
  ↓
asl-landmarks-stream (Kinesis)
  ↓
[THIS SERVICE] ← Polls and processes
  ↓
asl-letters-stream (Kinesis)
  ↓
[Future: Outbound Lambda → Client]
```

## 📁 Project Structure

```
letter-model-sevice/
├── main.py                 # Entry point - Kinesis consumer/producer
├── services/               # Core business logic
│   ├── asl_service.py     # ASL prediction service
│   └── keypoint_classifier.py  # TFLite model wrapper
├── utils/                  # Utility functions
│   └── tracer.py          # OpenTelemetry tracing setup
├── constant/               # Configuration constants
│   └── config.py
├── model/                  # TensorFlow Lite models
│   └── keypoint_classifier/
│       ├── keypoint_classifier.tflite
│       └── keypoint_classifier_label.csv
├── tests/                  # Unit tests
│   ├── conftest.py
│   └── test_asl_service.py
├── Dockerfile              # Container image definition
├── pyproject.toml          # Python dependencies
├── LOCAL_TESTING.md        # Comprehensive testing guide
└── test_local.sh           # Quick start script
```

## 🚀 Quick Start

### Option 1: Using the Test Script (Recommended)

```bash
cd src/letter-model-sevice
./test_local.sh
```

The script will:
- ✅ Check AWS credentials
- ✅ Verify Kinesis streams exist
- ✅ Validate model files
- ✅ Install dependencies
- ✅ Run unit tests (optional)
- ✅ Start the service

### Option 2: Manual Setup

1. **Set environment variables**:

```bash
export AWS_REGION="us-east-1"
export LANDMARKS_STREAM_NAME="asl-landmarks-stream"
export LETTERS_STREAM_NAME="asl-letters-stream"
export POLLING_INTERVAL="1"
export ENABLE_TRACING="false"
```

2. **Install dependencies**:

```bash
pip install uv
uv sync
```

3. **Run the service**:

```bash
python3 main.py

# delete the consumer after
ps aux | grep "[p]ython main.py" | awk '{print $2}' | xargs -r kill
```

### Option 3: Docker

```bash
docker build -t letter-asl-service:latest .

aws sso login
 
docker run --rm \
  -v /root/.aws/config:/home/appuser/.aws/config:ro \
  -v /root/.aws/credentials:/home/appuser/.aws/credentials:ro \
  -v /root/.aws/sso/cache:/home/appuser/.aws/sso/cache:rw \
  -e AWS_PROFILE=AdministratorAccess-837563944845 \
  -e AWS_REGION=us-east-1 \
  letter-asl-service:latest

# test send records to the stream
python3 test_kinesis_ingress.py wss://el9vhr7tx1.execute-api.us-east-1.amazonaws.com/dev meo-4 5
```

## 🧪 Testing

### Run Unit Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=services --cov=utils --cov-report=html
```

### End-to-End Testing

## 📊 Data Formats

### Input (from `asl-landmarks-stream`)

```json
{
  "session_id": "session-123",
  "connection_id": "conn-abc",
  "timestamp": "2025-10-05T12:00:00.000Z",
  "landmarks": [
    [0.5, 0.5],  // Wrist (x, y)
    [0.6, 0.5],  // Thumb CMC
    // ... 19 more landmarks (21 total)
  ],
  "metadata": {
    "source": "websocket"
  }
}
```

### Output (to `asl-letters-stream`)

```json
{
  "session_id": "session-123",
  "connection_id": "conn-abc",
  "timestamp": "2025-10-05T12:00:00.123Z",
  "prediction": "ASL A",
  "confidence": 0.95,
  "processing_time_ms": 15.23,
  "metadata": {
    "source": "letter-model-sevice",
    "model_type": "keypoint_classifier"
  }
}
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region | `us-east-1` |
| `LANDMARKS_STREAM_NAME` | Input Kinesis stream | `asl-landmarks-stream` |
| `LETTERS_STREAM_NAME` | Output Kinesis stream | `asl-letters-stream` |
| `POLLING_INTERVAL` | Seconds between polls | `1` |
| `ENABLE_TRACING` | Enable OpenTelemetry | `false` |

## 🔧 Development

### Adding New Features

1. Update `services/asl_service.py` for model changes
2. Add tests in `tests/test_asl_service.py`
3. Run tests: `pytest tests/ -v`
4. Update documentation

### Changing Models

To use a different TensorFlow Lite model:

1. Place model file in `model/keypoint_classifier/`
2. Update label CSV if needed
3. Adjust preprocessing in `asl_service.py` if input format changes

## 📈 Monitoring

### Metrics to Track

- **Processing latency**: `processing_time_ms` in output records
- **Throughput**: Records processed per second
- **Error rate**: Exceptions in logs
- **Confidence scores**: Distribution of prediction confidence

### Logs

Service logs include:
- Startup configuration
- Records processed count
- Prediction results (session_id, prediction, confidence)
- Errors and exceptions

## 🐛 Troubleshooting

### Service won't start

- Check AWS credentials: `aws sts get-caller-identity`
- Verify streams exist: `aws kinesis describe-stream --stream-name asl-landmarks-stream`
- Check model files: `ls model/keypoint_classifier/`

### No predictions appearing

- Check input stream has data: `aws kinesis get-records ...`
- Increase log level to DEBUG in `main.py`
- Verify shard iterator is valid

### Low confidence predictions

- Check landmark quality (all 21 landmarks present?)
- Verify preprocessing is correct
- Consider retraining model with more data

Log in to get the AWS credentials
```shell
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN
unset AWS_PROFILE

# Re-login to refresh SSO credentials
aws sso login --profile AdministratorAccess-837563944845

# Verify credentials work
aws sts get-caller-identity

# Check current profile
echo $AWS_PROFILE

aws sts get-caller-identity --profile AdministratorAccess-837563944845
# export access key id and secret key
aws configure export-credentials --profile AdministratorAccess-837563944845 --format env
```

Run unit test
```shell
python3 -m pytest tests/ -v
```

Check Kinesis
```shell
aws kinesis get-shard-iterator \
  --stream-name asl-letters-stream \
  --shard-id shardId-000000000003 \
  --shard-iterator-type TRIM \
  --query 'ShardIterator' \
  --output text


aws kinesis get-records --shard-iterator <shard-iterator>

# Returns just the raw ARN string instead of JSON.
# Example output: arn:aws:kinesis:us-east-1:837563944845:stream/asl-landmarks-stream
aws kinesis describe-stream --stream-name asl-landmarks-stream --query 'StreamDescription.StreamARN' --output text

# This one lists all EFO consumers registered to that stream
aws kinesis list-stream-consumers --stream-arn $(aws kinesis describe-stream --stream-name asl-landmarks-stream --query 'StreamDescription.StreamARN' --output text)
```