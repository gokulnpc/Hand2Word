# IAM Role for Outbound Lambda execution
resource "aws_iam_role" "lambda_outbound_role" {
  name = "asl-lambda-outbound-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "asl-lambda-outbound-role"
  }
}

# IAM Policy for DynamoDB and API Gateway Management API access
resource "aws_iam_policy" "lambda_outbound_policy" {
  name        = "asl-lambda-outbound-policy"
  description = "Policy for Outbound Lambda to query DynamoDB and push to WebSocket clients"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:GetItem",
          "dynamodb:DeleteItem"
        ]
        Resource = [
          aws_dynamodb_table.websocket_connections.arn,
          "${aws_dynamodb_table.websocket_connections.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "execute-api:ManageConnections"
        ]
        Resource = "${aws_apigatewayv2_api.websocket_api.execution_arn}/*/*/@connections/*"
      }
    ]
  })
}

# Attach Outbound policy to Lambda role
resource "aws_iam_role_policy_attachment" "lambda_outbound_attach" {
  role       = aws_iam_role.lambda_outbound_role.name
  policy_arn = aws_iam_policy.lambda_outbound_policy.arn
}

# Attach basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "lambda_outbound_basic_execution" {
  role       = aws_iam_role.lambda_outbound_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Create Lambda deployment package for outbound handler
data "archive_file" "outbound_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/outbound_handler/outbound_handler.py"
  output_path = "${path.module}/outbound_handler/outbound_handler.zip"
}

# Lambda function for outbound WebSocket communication
resource "aws_lambda_function" "outbound_lambda" {
  filename         = data.archive_file.outbound_lambda_zip.output_path
  function_name    = "asl-outbound-handler"
  role            = aws_iam_role.lambda_outbound_role.arn
  handler         = "outbound_handler.lambda_handler"
  source_code_hash = data.archive_file.outbound_lambda_zip.output_base64sha256
  runtime         = "python3.12"
  timeout         = 30
  memory_size     = 256

  environment {
    variables = {
      CONNECTIONS_TABLE_NAME = aws_dynamodb_table.websocket_connections.name
      API_GATEWAY_ENDPOINT   = aws_apigatewayv2_stage.api_stage.invoke_url
    }
  }

  tags = {
    Name = "asl-outbound-handler"
  }
}

# CloudWatch Log Group for Outbound Lambda
resource "aws_cloudwatch_log_group" "outbound_lambda_log_group" {
  name              = "/aws/lambda/${aws_lambda_function.outbound_lambda.function_name}"
  retention_in_days = 7

  tags = {
    Name = "asl-outbound-lambda-logs"
  }
}

# Outputs
output "outbound_lambda_function_name" {
  description = "Name of the outbound Lambda function"
  value       = aws_lambda_function.outbound_lambda.function_name
}

output "outbound_lambda_function_arn" {
  description = "ARN of the outbound Lambda function"
  value       = aws_lambda_function.outbound_lambda.arn
}

