# Lambda function for KB Submit
# Triggered by S3 uploads, starts Textract jobs, and updates DynamoDB

resource "aws_lambda_function" "kb_submit" {
  function_name = "asl-kb-submit-${var.environment}"
  role          = aws_iam_role.kb_submit_lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  timeout       = 60  # 1 minute (should be enough for starting Textract)
  memory_size   = 256  # 256 MB (cheapest option that's reasonable)

  # Placeholder for deployment package - you'll need to create this
  filename         = "${path.module}/lambda/kb-submit/deployment.zip"
  source_code_hash = fileexists("${path.module}/lambda/kb-submit/deployment.zip") ? filebase64sha256("${path.module}/lambda/kb-submit/deployment.zip") : null

  environment {
    variables = {
      KB_JOBS_TABLE          = aws_dynamodb_table.kb_jobs.name
      TEXTRACT_SNS_TOPIC_ARN = aws_sns_topic.textract_completion.arn
      TEXTRACT_SNS_ROLE_ARN  = aws_iam_role.textract_sns_role.arn
      ENVIRONMENT            = var.environment
    }
  }

  # Enable X-Ray tracing for dev (optional, minimal cost)
  tracing_config {
    mode = "PassThrough"  # Use Active for full tracing, PassThrough to save costs
  }

  tags = {
    Name        = "asl-kb-submit"
    Environment = var.environment
    Purpose     = "Process KB file uploads and start Textract jobs"
  }
}

# CloudWatch Log Group for Submit Lambda
resource "aws_cloudwatch_log_group" "kb_submit" {
  name              = "/aws/lambda/${aws_lambda_function.kb_submit.function_name}"
  retention_in_days = 7  # 7 days retention for dev (cost optimization)

  tags = {
    Name        = "asl-kb-submit-logs"
    Environment = var.environment
  }
}

# Lambda permission for S3 to invoke the function
resource "aws_lambda_permission" "allow_s3_kb_uploads" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.kb_submit.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.kb_uploads.arn
}

# Outputs
output "kb_submit_lambda_arn" {
  description = "ARN of KB Submit Lambda function"
  value       = aws_lambda_function.kb_submit.arn
}

output "kb_submit_lambda_name" {
  description = "Name of KB Submit Lambda function"
  value       = aws_lambda_function.kb_submit.function_name
}

