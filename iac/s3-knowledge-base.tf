# S3 bucket for knowledge base uploads
# Users upload PDF/TXT/CSV/MD files here: /<user_id>/<filename>

resource "aws_s3_bucket" "kb_uploads" {
  bucket = "asl-kb-uploads-${var.environment}"

  tags = {
    Name        = "asl-kb-uploads"
    Environment = var.environment
    Purpose     = "Knowledge base file uploads"
  }
}

# Enable versioning for data protection
resource "aws_s3_bucket_versioning" "kb_uploads" {
  bucket = aws_s3_bucket.kb_uploads.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "kb_uploads" {
  bucket = aws_s3_bucket.kb_uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rule to clean up old versions (cost optimization for dev)
resource "aws_s3_bucket_lifecycle_configuration" "kb_uploads" {
  bucket = aws_s3_bucket.kb_uploads.id

  rule {
    id     = "delete-old-versions"
    status = "Enabled"

    filter {}  # Apply to all objects

    noncurrent_version_expiration {
      noncurrent_days = 30  # Keep old versions for 30 days
    }
  }

  rule {
    id     = "delete-incomplete-uploads"
    status = "Enabled"

    filter {}  # Apply to all objects

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# S3 bucket notification to trigger Submit Lambda
resource "aws_s3_bucket_notification" "kb_uploads" {
  bucket = aws_s3_bucket.kb_uploads.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.kb_submit.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".pdf"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.kb_submit.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".txt"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.kb_submit.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".csv"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.kb_submit.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".md"
  }

  depends_on = [aws_lambda_permission.allow_s3_kb_uploads]
}

# S3 bucket for processed/raw text storage
# Stores extracted text from Textract: /<user_id>/<filename>.txt

resource "aws_s3_bucket" "kb_raw" {
  bucket = "asl-kb-raw-${var.environment}"

  tags = {
    Name        = "asl-kb-raw"
    Environment = var.environment
    Purpose     = "Knowledge base processed text storage"
  }
}

# Enable versioning for data protection
resource "aws_s3_bucket_versioning" "kb_raw" {
  bucket = aws_s3_bucket.kb_raw.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "kb_raw" {
  bucket = aws_s3_bucket.kb_raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Outputs
output "kb_uploads_bucket_name" {
  description = "S3 bucket name for knowledge base uploads"
  value       = aws_s3_bucket.kb_uploads.id
}

output "kb_uploads_bucket_arn" {
  description = "S3 bucket ARN for knowledge base uploads"
  value       = aws_s3_bucket.kb_uploads.arn
}

# S3 bucket for aliases storage
# Stores LLM-generated aliases/synonyms: /<user_id>/<filename>_aliases.json

resource "aws_s3_bucket" "kb_aliases" {
  bucket = "asl-kb-aliases-${var.environment}"

  tags = {
    Name        = "asl-kb-aliases"
    Environment = var.environment
    Purpose     = "Knowledge base aliases storage"
  }
}

# Enable versioning for data protection
resource "aws_s3_bucket_versioning" "kb_aliases" {
  bucket = aws_s3_bucket.kb_aliases.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "kb_aliases" {
  bucket = aws_s3_bucket.kb_aliases.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "kb_raw_bucket_name" {
  description = "S3 bucket name for processed text storage"
  value       = aws_s3_bucket.kb_raw.id
}

output "kb_raw_bucket_arn" {
  description = "S3 bucket ARN for processed text storage"
  value       = aws_s3_bucket.kb_raw.arn
}

output "kb_aliases_bucket_name" {
  description = "S3 bucket name for aliases storage"
  value       = aws_s3_bucket.kb_aliases.id
}

output "kb_aliases_bucket_arn" {
  description = "S3 bucket ARN for aliases storage"
  value       = aws_s3_bucket.kb_aliases.arn
}

