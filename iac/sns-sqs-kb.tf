# SNS topic for Textract job completion notifications
# Textract publishes to this topic when document analysis is complete

resource "aws_sns_topic" "textract_completion" {
  name = "asl-textract-completion-${var.environment}"

  tags = {
    Name        = "asl-textract-completion"
    Environment = var.environment
    Purpose     = "Textract job completion notifications"
  }
}

# SNS topic policy to allow Textract to publish
resource "aws_sns_topic_policy" "textract_completion" {
  arn = aws_sns_topic.textract_completion.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "textract.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.textract_completion.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# Data source to get current AWS account ID
data "aws_caller_identity" "current" {}

# SQS queue for processing Textract completion notifications
# This decouples SNS from Lambda and provides retry/DLQ capabilities

resource "aws_sqs_queue" "textract_completion_dlq" {
  name                      = "asl-textract-completion-dlq-${var.environment}"
  message_retention_seconds = 1209600  # 14 days (max retention)

  tags = {
    Name        = "asl-textract-completion-dlq"
    Environment = var.environment
    Purpose     = "Dead letter queue for failed Textract notifications"
  }
}

resource "aws_sqs_queue" "textract_completion" {
  name                       = "asl-textract-completion-${var.environment}"
  visibility_timeout_seconds = 300  # 5 minutes (should be >= Lambda timeout)
  message_retention_seconds  = 345600  # 4 days
  receive_wait_time_seconds  = 10  # Enable long polling (cost optimization)

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.textract_completion_dlq.arn
    maxReceiveCount     = 3  # Retry 3 times before sending to DLQ
  })

  tags = {
    Name        = "asl-textract-completion"
    Environment = var.environment
    Purpose     = "Queue for Textract completion notifications"
  }
}

# SQS queue policy to allow SNS to send messages
resource "aws_sqs_queue_policy" "textract_completion" {
  queue_url = aws_sqs_queue.textract_completion.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "sns.amazonaws.com"
        }
        Action   = "SQS:SendMessage"
        Resource = aws_sqs_queue.textract_completion.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.textract_completion.arn
          }
        }
      }
    ]
  })
}

# Subscribe SQS queue to SNS topic
resource "aws_sns_topic_subscription" "textract_to_sqs" {
  topic_arn = aws_sns_topic.textract_completion.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.textract_completion.arn
  
  # Enable raw message delivery to avoid SNS envelope
  raw_message_delivery = false
}

# Outputs
output "textract_completion_topic_arn" {
  description = "SNS topic ARN for Textract completion notifications"
  value       = aws_sns_topic.textract_completion.arn
}

output "textract_completion_queue_url" {
  description = "SQS queue URL for Textract completion"
  value       = aws_sqs_queue.textract_completion.url
}

output "textract_completion_queue_arn" {
  description = "SQS queue ARN for Textract completion"
  value       = aws_sqs_queue.textract_completion.arn
}

