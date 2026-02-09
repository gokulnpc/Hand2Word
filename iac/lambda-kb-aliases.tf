# Lambda function for generating term aliases using LLM
# Triggered by SQS messages when cleaned terms are ready

resource "aws_lambda_function" "kb_aliases" {
  function_name = "asl-kb-aliases-${var.environment}"
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"
  timeout       = 900  # 15 minutes (LLM calls can be slow)
  memory_size   = 1024  # More memory for LLM processing

  filename         = "${path.module}/lambda/kb-aliases/deployment.zip"
  source_code_hash = fileexists("${path.module}/lambda/kb-aliases/deployment.zip") ? filebase64sha256("${path.module}/lambda/kb-aliases/deployment.zip") : null

  role = aws_iam_role.kb_aliases_lambda.arn

  environment {
    variables = {
      KB_JOBS_TABLE     = aws_dynamodb_table.kb_jobs.name
      KB_RAW_BUCKET     = aws_s3_bucket.kb_raw.id
      KB_ALIASES_BUCKET = aws_s3_bucket.kb_aliases.id
      ENVIRONMENT       = var.environment
      MONGODB_URL       = var.mongodb_url  # MongoDB Atlas connection string
    }
  }

  tags = {
    Name        = "asl-kb-aliases"
    Environment = var.environment
    Purpose     = "Generate term aliases using LLM"
  }
}

# SQS trigger for Aliases Lambda
resource "aws_lambda_event_source_mapping" "kb_aliases_sqs" {
  event_source_arn = aws_sqs_queue.kb_aliases.arn
  function_name    = aws_lambda_function.kb_aliases.arn
  batch_size       = 1  # Process one job at a time (LLM calls are expensive)
  enabled          = true

  # Partial batch response
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 2  # Limit concurrent executions (cost control + rate limits)
  }
}

# CloudWatch Log Group for Aliases Lambda
resource "aws_cloudwatch_log_group" "kb_aliases_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.kb_aliases.function_name}"
  retention_in_days = 7  # Dev environment - short retention

  tags = {
    Name        = "asl-kb-aliases-logs"
    Environment = var.environment
  }
}

# Outputs
output "kb_aliases_lambda_arn" {
  description = "ARN of KB Aliases Lambda function"
  value       = aws_lambda_function.kb_aliases.arn
}

output "kb_aliases_lambda_name" {
  description = "Name of KB Aliases Lambda function"
  value       = aws_lambda_function.kb_aliases.function_name
}


