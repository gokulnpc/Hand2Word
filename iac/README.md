# AWS Infrastructure - ASL Recognition System

This repository contains Terraform configuration for provisioning a complete AWS infrastructure for the ASL (American Sign Language) Recognition System. The infrastructure is designed for development environments with cost optimization in mind.

## Architecture Overview

### System Components

The infrastructure consists of three main Terraform modules:

1. **`eks-cluster.tf`**: EKS cluster for model serving
2. **`kinesis-streams.tf`**: Data streams for real-time ingestion
3. **`lambda-ingress.tf`**: WebSocket API and Lambda handlers

### Data Flow Architecture

```
┌──────────────┐
│  Client      │
│  (app.py)    │
└──────┬───────┘
       │
       └──> WebSocket (API Gateway) ──> Lambda ──> Kinesis Streams
                                                      │
                                                      ├─> landmarks-stream (PK: session_id)
                                                      └─> letters-stream (PK: session_id)
                                                      
```

**Note**: In this architecture, the client connects only to API Gateway WebSocket. The EKS model serving service will be integrated as a downstream consumer of the Kinesis streams, not as a direct WebSocket endpoint for clients.

## Infrastructure Components

### 1. EKS Cluster (`eks-cluster.tf`)

#### Network Infrastructure
- **VPC**: Custom VPC with CIDR `10.0.0.0/16`
- **Public Subnet**: `10.0.1.0/24` (single AZ for cost optimization)
- **Private Subnet**: `10.0.10.0/24` (single AZ)
- **NAT Gateway**: Single NAT gateway for outbound traffic
- **Internet Gateway**: Public internet access

#### Kubernetes Infrastructure
- **EKS Cluster**: Managed Kubernetes control plane (v1.28)
- **Node Group**: Managed worker nodes (t3.small instances)
- **IAM Roles**: Service roles for cluster and nodes

### 2. Kinesis Data Streams (`kinesis-streams.tf`)

#### Landmarks Stream
- **Name**: `asl-landmarks-stream`
- **Purpose**: Stores raw hand landmark data
- **Partition Key**: `session_id`
- **Retention**: 24 hours
- **Shards**: 1 (provisioned mode)

#### Letters Stream
- **Name**: `asl-letters-stream`
- **Purpose**: Stores recognized ASL signs/letters
- **Partition Key**: `session_id`
- **Retention**: 24 hours
- **Shards**: 1 (provisioned mode)

### 3. Lambda & API Gateway (`lambda-ingress.tf`)

#### WebSocket API
- **Type**: API Gateway WebSocket API
- **Routes**:
  - `$connect`: Connection handler
  - `$disconnect`: Disconnection handler
  - `$default`: Default message handler
  - `sendlandmarks`: Landmark data handler

#### Lambda Function
- **Name**: `asl-ingress-handler`
- **Runtime**: Python 3.12
- **Memory**: 256 MB
- **Timeout**: 30 seconds
- **Permissions**: `kinesis:PutRecord`, `kinesis:PutRecords`

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **Terraform** (version >= 1.0.0)
3. **Python 3.12** for Lambda functions
4. **AWS IAM permissions** for:
   - EKS cluster management
   - Kinesis stream creation
   - Lambda function deployment
   - API Gateway management
   - VPC and networking resources

## AWS Profile Configuration

**IMPORTANT**: Before running any Terraform commands, export the correct AWS profile:

```bash
export AWS_PROFILE=AdministratorAccess-837563944845
```

This ensures Terraform uses the correct AWS SSO session credentials for account `837563944845`.

## Deployment Instructions

### Step 1: Initialize Terraform

```bash
cd iac/
export AWS_PROFILE=AdministratorAccess-837563944845
terraform init
```

### Step 2: Review Configuration

Review and customize variables in `variables.tf`:
- `region`: AWS region (default: `us-east-1`)
- `instance_type`: Node instance type (default: `t3.small`)
- `kubernetes_version`: EKS version (default: `1.28`)
- `api_gateway_stage`: API Gateway stage (default: `dev`)

### Step 3: Plan Deployment

```bash
terraform plan
```

### Step 4: Deploy Infrastructure

```bash
terraform apply
```

Review the plan and type `yes` to confirm.

### Step 5: Get Outputs

After deployment, get the WebSocket endpoint:

```bash
terraform output websocket_api_endpoint
```

Example output:
```
wss://abc123.execute-api.us-east-1.amazonaws.com/dev
```

### Step 6: Configure kubectl for EKS

```bash
aws eks update-kubeconfig --region us-east-1 --name asl-cluster
kubectl get nodes
```

## Testing the Infrastructure

### Test 1: WebSocket Connection to Kinesis

```bash
# Install wscat if not already installed
npm install -g wscat

# Connect to the WebSocket API
wscat -c wss://YOUR_API_ENDPOINT/dev

# Send a test message
{"action": "sendlandmarks", "session_id": "test-session", "data": [[0.1, 0.2, 0.3]]}
```

### Test 2: Verify Kinesis Stream

```bash
# Describe the stream
aws kinesis describe-stream --stream-name asl-landmarks-stream

# Get records (replace SHARD_ITERATOR with actual iterator)
aws kinesis get-shard-iterator \
  --stream-name asl-landmarks-stream \
  --shard-id shardId-000000000000 \
  --shard-iterator-type LATEST

aws kinesis get-records --shard-iterator YOUR_SHARD_ITERATOR
```

### Test 3: Client Application

Update `app.py` to connect to API Gateway WebSocket:

```bash
python app.py \
  --kinesis_ws_url $WS_ENDPOINT \
  --session_id my-session-123
```

## Infrastructure Files

| File | Purpose |
|------|---------|
| `eks-cluster.tf` | EKS cluster, VPC, networking, and node groups |
| `kinesis-streams.tf` | Kinesis data streams for landmarks and letters |
| `lambda-ingress.tf` | Lambda functions and API Gateway WebSocket |
| `variables.tf` | Input variables for all modules |
| `lambda/ingress_handler.py` | Lambda function code for WebSocket ingress |

## Cost Optimization (Development)

### Cost Optimization Tips

1. **Use On-Demand Kinesis**: Switch to on-demand mode for variable workloads
2. **Stop EKS when not in use**: Terminate nodes during off-hours
3. **Lambda Reserved Concurrency**: Limit concurrent executions
4. **CloudWatch Logs**: Set retention periods (7 days for dev)

## Monitoring

### CloudWatch Metrics

- **Kinesis**: IncomingRecords, IncomingBytes, WriteProvisionedThroughputExceeded
- **Lambda**: Invocations, Duration, Errors, Throttles
- **API Gateway**: MessageCount, ConnectionCount, IntegrationLatency
- **EKS**: Node CPU/Memory utilization

### CloudWatch Logs

- Lambda logs: `/aws/lambda/asl-ingress-handler`
- API Gateway logs: Enabled in stage settings
- EKS logs: Control plane logs (optional)

## Cost Management - Destroying Expensive Resources

To save costs during development, you can destroy the most expensive resources while keeping the rest:

### Destroy EKS Resources (~$132/month savings)

```bash
export AWS_PROFILE=AdministratorAccess-837563944845

# Destroy EKS node group and cluster
terraform destroy \
  -target=aws_eks_node_group.asl_node_group \
  -target=aws_eks_cluster.asl_cluster

# Destroy NAT Gateway and Elastic IP
terraform destroy \
  -target=aws_nat_gateway.asl_nat_gateway \
  -target=aws_eip.asl_nat_eip
```

This saves approximately:
- EKS Control Plane: $72/month
- EC2 Node (t3.small): $15/month
- NAT Gateway: $45/month
- **Total savings: ~$132/month**

### Recreate EKS Resources When Needed

To recreate the destroyed EKS infrastructure:

```bash
export AWS_PROFILE=AdministratorAccess-837563944845

# Recreate NAT Gateway and EIP first
terraform apply \
  -target=aws_eip.asl_nat_eip \
  -target=aws_nat_gateway.asl_nat_gateway

# Then recreate EKS cluster and node group
terraform apply \
  -target=aws_eks_cluster.asl_cluster \
  -target=aws_eks_node_group.asl_node_group

# Update kubectl configuration
aws eks update-kubeconfig --region us-east-1 --name asl-cluster
```

**Note**: The VPC, subnets, and routing infrastructure remain intact for quick recreation.

## Cleanup - Full Destroy

To destroy all resources permanently:

```bash
export AWS_PROFILE=AdministratorAccess-837563944845
terraform destroy
```

**Warning**: This will permanently delete:
- EKS cluster and all workloads
- Kinesis streams and data
- Lambda functions
- API Gateway
- VPC and networking resources
- Knowledge Base infrastructure (S3, DynamoDB, SNS, SQS)

## Troubleshooting

### Lambda Can't Write to Kinesis

Check IAM permissions:
```bash
aws iam get-role-policy --role-name asl-lambda-ingress-role --policy-name asl-lambda-kinesis-policy
```

### WebSocket Connection Fails

1. Check API Gateway deployment:
   ```bash
   aws apigatewayv2 get-apis
   ```

2. Check Lambda logs:
   ```bash
   aws logs tail /aws/lambda/asl-ingress-handler --follow
   ```

### EKS Nodes Not Joining

1. Check node group status:
   ```bash
   aws eks describe-nodegroup --cluster-name asl-cluster --nodegroup-name asl-node-group
   ```

2. Verify IAM roles and security groups

## Architecture Decisions

### Why Single AZ?
- **Cost**: 50% reduction in NAT gateway costs
- **Suitable for**: Development and testing environments
- **Trade-off**: No high availability

### Why Kinesis?
- **Real-time**: Sub-second latency for streaming data
- **Durable**: 24-hour retention for replay
- **Scalable**: Partition by session_id for parallel processing

### Why Lambda + API Gateway?
- **Serverless**: No infrastructure management
- **Cost-effective**: Pay per request
- **Scalable**: Auto-scales with connections

## Next Steps

1. **Deploy Model Serving**: Deploy the letter-model-sevice to EKS
2. **Add Processing Pipeline**: Create Lambda consumers for Kinesis streams
3. **Add Monitoring**: Set up CloudWatch dashboards and alarms
4. **Add CI/CD**: Implement automated deployments
5. **Production Hardening**: Move to multi-AZ for production

## Debug command

### Kinesis stream logs:
```shell
# see how the stream configured
aws kinesis describe-stream --stream-name asl-landmarks-stream

# Returns a single-use iterator token to fetch records.
aws kinesis get-shard-iterator --stream-name asl-landmarks-stream --shard-id shardId-000000000000 --shard-iterator-type TRIM_HORIZON --query 'ShardIterator' --output text

# read the record (decoded)
aws kinesis get-records --shard-iterator "AAAAAAAAAAF777nXW6nfKp3J3mixgD3wDAa2qozzfN/00ZBlKSbNAS79lcxfy9HZCOqNZnLokdOnTdv2grX+fh7p8ZEpefcNt/CKYLG/oc0xmr0Q7+C7z4AHD4Gct9ZGqrReL0OtpzrsToADU100pJ+220TzeplQAmUOiV4AYv+vDkGkF8IArYhLuDEY0UEdPDeVSmAFTVQjBmIDK47ZHkO8zOUoBkhEjQ47xxqwag0zZ+3INQbPquAfkHP5URfvw7XASIazUEU=" --limit 5
```


### AWS logs to check if dynamodb is writing connection

```shell
aws logs tail /aws/lambda/asl-ingress-handler --since 5m --format short
```

## Knowledge Base Infrastructure Debug Commands

### End-to-End KB Testing Flow

```bash
# Set AWS profile for all commands
export AWS_PROFILE=AdministratorAccess-837563944845

# 1. Upload a PDF to trigger the pipeline
aws s3 cp /path/to/document.pdf s3://asl-kb-uploads-dev/testuser/document.pdf

# 2. Monitor Submit Lambda logs (watches for S3 trigger and Textract job start)
aws logs tail /aws/lambda/asl-kb-submit-dev --since 2m --format short

# 3. Check Textract job status (replace JOB_ID with actual job ID from logs)
aws textract get-document-analysis --job-id JOB_ID --query '[JobStatus, StatusMessage]' --output text

# 4. Check SQS queue depth (should have message when Textract completes)
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/837563944845/asl-textract-completion-dev \
  --attribute-names ApproximateNumberOfMessages

# 5. Monitor Ingest Lambda logs (processes Textract results)
aws logs tail /aws/lambda/asl-kb-ingest-dev --since 2m --format short

# 6. Verify DynamoDB job status (should show INGESTED)
aws dynamodb get-item \
  --table-name asl-kb-jobs-dev \
  --key '{"job_id":{"S":"JOB_ID"}}' \
  --query 'Item.[status.S, raw_text_s3_key.S, user_id.S]' \
  --output table

# 7. List extracted files in kb_raw bucket
aws s3 ls s3://asl-kb-raw-dev/testuser/ --recursive

# 8. Preview extracted text
aws s3 cp s3://asl-kb-raw-dev/testuser/document.txt - | head -20

# 9. View extraction metadata
aws s3 cp s3://asl-kb-raw-dev/testuser/document_metadata.json - | python3 -m json.tool
```

### KB Monitoring Commands

```bash
# Count total jobs processed
aws dynamodb scan --table-name asl-kb-jobs-dev --select COUNT --query 'Count'

# List all jobs by status
aws dynamodb query \
  --table-name asl-kb-jobs-dev \
  --index-name status-index \
  --key-condition-expression "status = :status" \
  --expression-attribute-values '{":status":{"S":"INGESTED"}}' \
  --query 'Items[*].[job_id.S, user_id.S, s3_key.S]' \
  --output table

# List all jobs for a specific user
aws dynamodb query \
  --table-name asl-kb-jobs-dev \
  --index-name user_id-index \
  --key-condition-expression "user_id = :uid" \
  --expression-attribute-values '{":uid":{"S":"testuser"}}' \
  --query 'Items[*].[job_id.S, status.S, created_at.S]' \
  --output table

# Check DLQ for failed messages
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/837563944845/asl-textract-completion-dlq-dev \
  --attribute-names ApproximateNumberOfMessages

# View SNS topic subscriptions
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:us-east-1:837563944845:asl-textract-completion-dev

# Check S3 bucket sizes
aws s3 ls s3://asl-kb-uploads-dev --recursive --summarize | tail -2
aws s3 ls s3://asl-kb-raw-dev --recursive --summarize | tail -2
```

### KB Debugging Commands

```bash
# Get full Textract results (all text lines)
aws textract get-document-analysis \
  --job-id JOB_ID \
  --query 'Blocks[?BlockType==`LINE`].Text' \
  --output json

# Get Textract table data
aws textract get-document-analysis \
  --job-id JOB_ID \
  --query 'Blocks[?BlockType==`TABLE`]' \
  --output json

# Manually receive SQS message (for debugging)
aws sqs receive-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/837563944845/asl-textract-completion-dev \
  --max-number-of-messages 1 \
  --query 'Messages[0].Body' \
  --output text | python3 -m json.tool

# Delete SQS message after manual processing (replace RECEIPT_HANDLE)
aws sqs delete-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/837563944845/asl-textract-completion-dev \
  --receipt-handle "RECEIPT_HANDLE"

# Check Lambda function configuration
aws lambda get-function-configuration \
  --function-name asl-kb-submit-dev \
  --query '[FunctionName, Runtime, MemorySize, Timeout, Environment.Variables]' \
  --output json

aws lambda get-function-configuration \
  --function-name asl-kb-ingest-dev \
  --query '[FunctionName, Runtime, MemorySize, Timeout, Environment.Variables]' \
  --output json

# Check Lambda event source mapping (SQS trigger)
aws lambda list-event-source-mappings \
  --function-name asl-kb-ingest-dev \
  --query 'EventSourceMappings[*].[UUID, State, BatchSize, EventSourceArn]' \
  --output table

# Stream Lambda logs in real-time
aws logs tail /aws/lambda/asl-kb-submit-dev --follow
aws logs tail /aws/lambda/asl-kb-ingest-dev --follow

# Check IAM role permissions
aws iam get-role --role-name asl-kb-submit-lambda-dev --query 'Role.Arn'
aws iam list-role-policies --role-name asl-kb-submit-lambda-dev
aws iam get-role-policy --role-name asl-kb-submit-lambda-dev --policy-name textract-access

# Verify S3 bucket notifications
aws s3api get-bucket-notification-configuration --bucket asl-kb-uploads-dev
```

### KB Cost Monitoring

```bash
# Estimate Textract usage (check CloudWatch metrics)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Textract \
  --metric-name PageCount \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Sum

# Check Lambda invocation counts
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=asl-kb-submit-dev \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Sum

# Check S3 storage usage
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name BucketSizeBytes \
  --dimensions Name=BucketName,Value=asl-kb-uploads-dev Name=StorageType,Value=StandardStorage \
  --start-time $(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Average
```
