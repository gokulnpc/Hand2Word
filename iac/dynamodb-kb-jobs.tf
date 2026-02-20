# DynamoDB table to track knowledge base processing jobs
# Stores Textract job status and metadata for each uploaded file

resource "aws_dynamodb_table" "kb_jobs" {
  name         = "asl-kb-jobs-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"  # On-demand pricing for dev (cheapest for low traffic)
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"  # Textract JobId
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  # GSI to query jobs by user_id
  global_secondary_index {
    name            = "user_id-index"
    hash_key        = "user_id"
    range_key       = "status"
    projection_type = "ALL"
  }

  # GSI to query jobs by status (useful for monitoring/cleanup)
  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    projection_type = "ALL"
  }

  # Enable TTL to automatically clean up old completed jobs (cost optimization)
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # Enable point-in-time recovery for data protection (minimal cost)
  point_in_time_recovery {
    enabled = false  # Disabled for dev to save costs
  }

  tags = {
    Name        = "asl-kb-jobs"
    Environment = var.environment
    Purpose     = "Track knowledge base file processing jobs"
  }
}

# Outputs
output "kb_jobs_table_name" {
  description = "DynamoDB table name for KB jobs"
  value       = aws_dynamodb_table.kb_jobs.name
}

output "kb_jobs_table_arn" {
  description = "DynamoDB table ARN for KB jobs"
  value       = aws_dynamodb_table.kb_jobs.arn
}

