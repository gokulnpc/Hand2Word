# ElastiCache Redis for Word Resolver Session State
# Using cache.t3.micro for cost-effective development

resource "aws_security_group" "redis" {
  name        = "asl-redis-sg"
  description = "Security group for ElastiCache Redis"
  vpc_id      = aws_vpc.asl_vpc.id

  ingress {
    description = "Redis from EKS nodes"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [
      aws_subnet.asl_private_subnet_1.cidr_block,
      aws_subnet.asl_private_subnet_2.cidr_block
    ]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "asl-redis-sg"
    Environment = "dev"
  }
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "asl-redis-subnet-group"
  subnet_ids = [
    aws_subnet.asl_private_subnet_1.id,
    aws_subnet.asl_private_subnet_2.id
  ]

  tags = {
    Name        = "asl-redis-subnet-group"
    Environment = "dev"
  }
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "asl-word-resolver"
  engine               = "redis"
  engine_version       = "7.0"
  node_type            = "cache.t3.micro"  # Cost-effective for dev
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [aws_security_group.redis.id]

  # Cost optimization
  apply_immediately    = true
  maintenance_window   = "sun:05:00-sun:06:00"
  snapshot_window      = "03:00-04:00"
  snapshot_retention_limit = 0  # No snapshots for dev

  tags = {
    Name        = "asl-word-resolver-redis"
    Environment = "dev"
    Purpose     = "Session state for word resolver"
  }
}

# Outputs
output "redis_endpoint" {
  description = "ElastiCache Redis endpoint"
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = aws_elasticache_cluster.redis.port
}

output "redis_connection_string" {
  description = "Full Redis connection string"
  value       = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:${aws_elasticache_cluster.redis.port}"
  sensitive   = true
}

