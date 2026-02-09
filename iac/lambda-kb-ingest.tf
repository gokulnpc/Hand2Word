# Lambda function for ingesting processed Textract results
# Triggered by SQS messages from Textract completion SNS topic

resource "aws_lambda_function" "kb_ingest" {
  function_name = "asl-kb-ingest-${var.environment}"
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  timeout       = 300  # 5 minutes (Textract results can be large)
  memory_size   = 512  # More memory for processing large documents

  filename         = "${path.module}/lambda/kb-ingest/deployment.zip"
  source_code_hash = fileexists("${path.module}/lambda/kb-ingest/deployment.zip") ? filebase64sha256("${path.module}/lambda/kb-ingest/deployment.zip") : null

  role = aws_iam_role.kb_ingest_lambda.arn

  environment {
    variables = {
      KB_JOBS_TABLE             = aws_dynamodb_table.kb_jobs.name
      KB_RAW_BUCKET             = aws_s3_bucket.kb_raw.id
      KB_TERMS_READY_TOPIC_ARN  = aws_sns_topic.kb_terms_ready.arn
      ENVIRONMENT               = var.environment
    }
  }

  tags = {
    Name        = "asl-kb-ingest"
    Environment = var.environment
    Purpose     = "Process Textract results and upload to S3"
  }
}

# SQS trigger for Ingest Lambda
resource "aws_lambda_event_source_mapping" "kb_ingest_sqs" {
  event_source_arn = aws_sqs_queue.textract_completion.arn
  function_name    = aws_lambda_function.kb_ingest.arn
  batch_size       = 5  # Process up to 5 messages at once
  enabled          = true

  # Partial batch response - allow successful messages to be deleted even if some fail
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 5  # Limit concurrent executions for cost control in dev
  }
}

# CloudWatch Log Group for Ingest Lambda
resource "aws_cloudwatch_log_group" "kb_ingest_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.kb_ingest.function_name}"
  retention_in_days = 7  # Dev environment - short retention

  tags = {
    Name        = "asl-kb-ingest-logs"
    Environment = var.environment
  }
}

# Outputs
output "kb_ingest_lambda_arn" {
  description = "ARN of KB Ingest Lambda function"
  value       = aws_lambda_function.kb_ingest.arn
}

output "kb_ingest_lambda_name" {
  description = "Name of KB Ingest Lambda function"
  value       = aws_lambda_function.kb_ingest.function_name
}

