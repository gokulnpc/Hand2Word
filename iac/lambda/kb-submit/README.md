# KB Submit Lambda

This Lambda function is triggered when files are uploaded to the `kb_uploads` S3 bucket.

## Purpose

- Processes new file uploads for the knowledge base
- Creates job tracking records in DynamoDB
- Starts Textract async jobs for PDF files
- Marks text files (TXT/CSV/MD) as ready for immediate ingestion

## Deployment

To create the deployment package:

```bash
cd lambda/kb-submit
pip install -r requirements.txt -t .
zip -r deployment.zip .
```

## Environment Variables

- `KB_JOBS_TABLE`: DynamoDB table name for job tracking
- `TEXTRACT_SNS_TOPIC_ARN`: SNS topic ARN for Textract completion notifications
- `TEXTRACT_SNS_ROLE_ARN`: IAM role ARN for Textract to publish to SNS
- `ENVIRONMENT`: Environment name (dev/staging/prod)

## Flow

1. S3 upload triggers Lambda
2. Extract file details (bucket, key, user_id)
3. Compute `request_id` for idempotency
4. Check file type:
   - **PDF**: Start Textract async job → status: `RUNNING`
   - **TXT/CSV/MD**: Skip Textract → status: `SUCCEEDED`
5. Create job record in DynamoDB
6. Textract publishes completion to SNS (for PDF files)

