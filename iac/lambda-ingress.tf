# IAM Role for Lambda execution
resource "aws_iam_role" "lambda_ingress_role" {
  name = "asl-lambda-ingress-role"

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
    Name = "asl-lambda-ingress-role"
  }
}

# IAM Policy for Kinesis and DynamoDB access
resource "aws_iam_policy" "lambda_kinesis_dynamodb_policy" {
  name        = "asl-lambda-kinesis-dynamodb-policy"
  description = "Policy for Lambda to write to Kinesis streams and DynamoDB"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:PutRecord",
          "kinesis:PutRecords"
        ]
        Resource = [
          aws_kinesis_stream.landmarks_stream.arn,
          aws_kinesis_stream.letters_stream.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:GetItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.websocket_connections.arn,
          "${aws_dynamodb_table.websocket_connections.arn}/index/*"
        ]
      }
    ]
  })
}

# Attach Kinesis and DynamoDB policy to Lambda role
resource "aws_iam_role_policy_attachment" "lambda_kinesis_dynamodb_attach" {
  role       = aws_iam_role.lambda_ingress_role.name
  policy_arn = aws_iam_policy.lambda_kinesis_dynamodb_policy.arn
}

# Attach basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_ingress_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Create Lambda deployment package
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/ingress_handler.py"
  output_path = "${path.module}/lambda/ingress_handler.zip"
}

# Lambda function for WebSocket ingress
resource "aws_lambda_function" "ingress_lambda" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "asl-ingress-handler"
  role            = aws_iam_role.lambda_ingress_role.arn
  handler         = "ingress_handler.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime         = "python3.12"
  timeout         = 30
  memory_size     = 256

  environment {
    variables = {
      LANDMARKS_STREAM_NAME   = aws_kinesis_stream.landmarks_stream.name
      LETTERS_STREAM_NAME     = aws_kinesis_stream.letters_stream.name
      CONNECTIONS_TABLE_NAME  = aws_dynamodb_table.websocket_connections.name
    }
  }

  tags = {
    Name = "asl-ingress-handler"
  }
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${aws_lambda_function.ingress_lambda.function_name}"
  retention_in_days = 7

  tags = {
    Name = "asl-lambda-logs"
  }
}

# API Gateway WebSocket API
resource "aws_apigatewayv2_api" "websocket_api" {
  name                       = "asl-websocket-api"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"

  tags = {
    Name = "asl-websocket-api"
  }
}

# Lambda integration for API Gateway
resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id           = aws_apigatewayv2_api.websocket_api.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ingress_lambda.invoke_arn
}

# Routes for WebSocket API
resource "aws_apigatewayv2_route" "connect_route" {
  api_id    = aws_apigatewayv2_api.websocket_api.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_route" "disconnect_route" {
  api_id    = aws_apigatewayv2_api.websocket_api.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_route" "default_route" {
  api_id    = aws_apigatewayv2_api.websocket_api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_route" "sendlandmarks_route" {
  api_id    = aws_apigatewayv2_api.websocket_api.id
  route_key = "sendlandmarks"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

# API Gateway deployment
resource "aws_apigatewayv2_deployment" "api_deployment" {
  api_id = aws_apigatewayv2_api.websocket_api.id

  depends_on = [
    aws_apigatewayv2_route.connect_route,
    aws_apigatewayv2_route.disconnect_route,
    aws_apigatewayv2_route.default_route,
    aws_apigatewayv2_route.sendlandmarks_route
  ]
}

# API Gateway stage
resource "aws_apigatewayv2_stage" "api_stage" {
  api_id        = aws_apigatewayv2_api.websocket_api.id
  name          = var.api_gateway_stage
  deployment_id = aws_apigatewayv2_deployment.api_deployment.id

  default_route_settings {
    throttling_burst_limit = 500
    throttling_rate_limit  = 100
  }

  tags = {
    Name = "asl-websocket-stage"
  }
}

# Lambda permission for API Gateway to invoke
resource "aws_lambda_permission" "api_gateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingress_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket_api.execution_arn}/*/*"
}

# Outputs
output "websocket_api_endpoint" {
  description = "WebSocket API endpoint URL"
  value       = "${aws_apigatewayv2_stage.api_stage.invoke_url}"
}

output "websocket_api_id" {
  description = "WebSocket API ID"
  value       = aws_apigatewayv2_api.websocket_api.id
}

output "lambda_function_name" {
  description = "Name of the ingress Lambda function"
  value       = aws_lambda_function.ingress_lambda.function_name
}

output "lambda_function_arn" {
  description = "ARN of the ingress Lambda function"
  value       = aws_lambda_function.ingress_lambda.arn
}

