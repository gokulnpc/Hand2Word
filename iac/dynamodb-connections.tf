# DynamoDB table to store WebSocket connectionId ↔ session_id mappings
# This is used by the Outbound Lambda to know which connectionId to push messages to

resource "aws_dynamodb_table" "websocket_connections" {
  name         = "asl-websocket-connections"
  billing_mode = "PAY_PER_REQUEST"  # On-demand pricing for dev environment
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  attribute {
    name = "session_id"
    type = "S"
  }

  # Global Secondary Index to query by session_id
  # This allows Outbound Lambda to find connectionId given a session_id
  global_secondary_index {
    name            = "session_id-index"
    hash_key        = "session_id"
    projection_type = "ALL"
  }

  # Enable TTL to automatically remove stale connections
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "asl-websocket-connections"
    Environment = "dev"
    Purpose     = "Store WebSocket connectionId to session_id mappings"
  }
}

# Output the table name
output "dynamodb_connections_table_name" {
  description = "DynamoDB table name for WebSocket connections"
  value       = aws_dynamodb_table.websocket_connections.name
}

output "dynamodb_connections_table_arn" {
  description = "DynamoDB table ARN for WebSocket connections"
  value       = aws_dynamodb_table.websocket_connections.arn
}

