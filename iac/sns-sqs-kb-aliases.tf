# SNS topic and SQS queue for KB term alias generation
# Triggered after text cleaning/deduplication completes

# ============================================================
# SNS Topic: Term Processing Completion
# ============================================================

resource "aws_sns_topic" "kb_terms_ready" {
  name = "asl-kb-terms-ready-${var.environment}"

  tags = {
    Name        = "asl-kb-terms-ready"
    Environment = var.environment
    Purpose     = "Notify when cleaned terms are ready for alias generation"
  }
}

# SNS topic policy to allow Lambda to publish
resource "aws_sns_topic_policy" "kb_terms_ready" {
  arn = aws_sns_topic.kb_terms_ready.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.kb_terms_ready.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# ============================================================
# SQS Queue: Aliases Processing Queue
# ============================================================

# Dead Letter Queue for failed alias generation
resource "aws_sqs_queue" "kb_aliases_dlq" {
  name                      = "asl-kb-aliases-dlq-${var.environment}"
  message_retention_seconds = 1209600  # 14 days (max retention)

  tags = {
    Name        = "asl-kb-aliases-dlq"
    Environment = var.environment
    Purpose     = "Dead letter queue for failed alias generation"
  }
}

# Main queue for alias generation
resource "aws_sqs_queue" "kb_aliases" {
  name                       = "asl-kb-aliases-${var.environment}"
  visibility_timeout_seconds = 900  # 15 minutes (LLM calls can be slow)
  message_retention_seconds  = 345600  # 4 days
  receive_wait_time_seconds  = 10  # Enable long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.kb_aliases_dlq.arn
    maxReceiveCount     = 3  # Retry 3 times before sending to DLQ
  })

  tags = {
    Name        = "asl-kb-aliases"
    Environment = var.environment
    Purpose     = "Queue for LLM alias generation processing"
  }
}

# SQS queue policy to allow SNS to send messages
resource "aws_sqs_queue_policy" "kb_aliases" {
  queue_url = aws_sqs_queue.kb_aliases.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "sns.amazonaws.com"
        }
        Action   = "SQS:SendMessage"
        Resource = aws_sqs_queue.kb_aliases.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.kb_terms_ready.arn
          }
        }
      }
    ]
  })
}

# Subscribe SQS queue to SNS topic
resource "aws_sns_topic_subscription" "kb_aliases_sqs" {
  topic_arn = aws_sns_topic.kb_terms_ready.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.kb_aliases.arn
  
  # Raw message delivery for easier processing
  raw_message_delivery = false
}

# ============================================================
# Outputs
# ============================================================

output "kb_terms_ready_topic_arn" {
  description = "SNS topic ARN for terms processing completion"
  value       = aws_sns_topic.kb_terms_ready.arn
}

output "kb_aliases_queue_url" {
  description = "SQS queue URL for alias generation"
  value       = aws_sqs_queue.kb_aliases.url
}

output "kb_aliases_queue_arn" {
  description = "SQS queue ARN for alias generation"
  value       = aws_sqs_queue.kb_aliases.arn
}

output "kb_aliases_dlq_url" {
  description = "Dead letter queue URL for failed alias generation"
  value       = aws_sqs_queue.kb_aliases_dlq.url
}

