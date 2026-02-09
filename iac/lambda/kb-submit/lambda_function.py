"""
KB Submit Lambda Function
Triggered by S3 uploads to kb_uploads bucket.
- Creates job record in DynamoDB
- Starts Textract async job for PDF files
- Skips Textract for TXT/CSV/MD files and marks them ready for ingestion
"""

import json
import os
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any
import boto3
from urllib.parse import unquote_plus

# AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
textract_client = boto3.client('textract')

# Environment variables
KB_JOBS_TABLE = os.environ['KB_JOBS_TABLE']
TEXTRACT_SNS_TOPIC_ARN = os.environ['TEXTRACT_SNS_TOPIC_ARN']
TEXTRACT_SNS_ROLE_ARN = os.environ['TEXTRACT_SNS_ROLE_ARN']
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')

# DynamoDB table
kb_jobs_table = dynamodb.Table(KB_JOBS_TABLE)


def compute_request_id(bucket: str, key: str, etag: str) -> str:
    """Compute a stable request_id from bucket, key, and etag for idempotency."""
    data = f"{bucket}|{key}|{etag}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def extract_user_id(s3_key: str) -> str:
    """Extract user_id from S3 key path: /<user_id>/<filename>"""
    parts = s3_key.split('/')
    if len(parts) >= 2:
        return parts[0] if parts[0] else parts[1]
    return "unknown"


def is_pdf_file(filename: str) -> bool:
    """Check if file is a PDF that needs Textract processing."""
    return filename.lower().endswith('.pdf')


def lambda_handler(event, context):
    """
    Main Lambda handler for S3 upload events.
    
    Flow:
    1. Extract S3 event details (bucket, key, etag)
    2. Compute request_id for idempotency
    3. Create job record in DynamoDB
    4. If PDF: Start Textract async job
    5. If TXT/CSV/MD: Skip Textract, mark as ready for ingestion
    """
    print(f"Event: {json.dumps(event)}")
    
    try:
        # Parse S3 event
        for record in event['Records']:
            # Get S3 details
            s3_bucket = record['s3']['bucket']['name']
            s3_key = unquote_plus(record['s3']['object']['key'])
            s3_etag = record['s3']['object'].get('eTag', '')
            
            print(f"Processing: s3://{s3_bucket}/{s3_key}")
            
            # Compute request_id for idempotency
            request_id = compute_request_id(s3_bucket, s3_key, s3_etag)
            
            # Extract user_id from S3 key
            user_id = extract_user_id(s3_key)
            
            # Get file metadata
            try:
                head_response = s3_client.head_object(Bucket=s3_bucket, Key=s3_key)
                file_size = head_response.get('ContentLength', 0)
            except Exception as e:
                print(f"Error getting file metadata: {str(e)}")
                file_size = 0
            
            # Determine if file needs Textract processing
            needs_textract = is_pdf_file(s3_key)
            
            # Create job record in DynamoDB
            timestamp = datetime.now(timezone.utc).isoformat()
            
            if needs_textract:
                # Start Textract async job
                print(f"Starting Textract job for PDF: {s3_key}")
                
                try:
                    # Log parameters for debugging
                    print(f"Textract params - Bucket: {s3_bucket}, Key: {s3_key}")
                    print(f"SNS Topic ARN: {TEXTRACT_SNS_TOPIC_ARN}")
                    print(f"SNS Role ARN: {TEXTRACT_SNS_ROLE_ARN}")
                    
                    textract_response = textract_client.start_document_analysis(
                        DocumentLocation={
                            'S3Object': {
                                'Bucket': s3_bucket,
                                'Name': s3_key
                            }
                        },
                        FeatureTypes=['TABLES', 'FORMS'],  # Extract tables and forms
                        NotificationChannel={
                            'SNSTopicArn': TEXTRACT_SNS_TOPIC_ARN,
                            'RoleArn': TEXTRACT_SNS_ROLE_ARN
                        },
                        JobTag=f"{request_id}"
                    )
                    print(f"JobTag: {user_id}|{s3_key}|{request_id}")
                    #print(f"✓ Textract started without NotificationChannel - this means the PDF and permissions are OK")
                    
                    job_id = textract_response['JobId']
                    print(f"Textract job started: {job_id}")
                    
                    # Create DynamoDB record with RUNNING status
                    kb_jobs_table.put_item(
                        Item={
                            'job_id': job_id,
                            'request_id': request_id,
                            'user_id': user_id,
                            's3_bucket': s3_bucket,
                            's3_key': s3_key,
                            'etag': s3_etag,
                            'file_size': file_size,
                            'status': 'RUNNING',
                            'created_at': timestamp,
                            'last_polled_at': timestamp,
                            'ttl': int(datetime.now(timezone.utc).timestamp()) + (30 * 24 * 60 * 60)  # 30 days TTL
                        }
                    )
                    
                    print(f"Job record created: {job_id}")
                    
                except Exception as e:
                    print(f"Error starting Textract job: {str(e)}")
                    
                    # Create DynamoDB record with FAILED status
                    kb_jobs_table.put_item(
                        Item={
                            'job_id': request_id,  # Use request_id as job_id
                            'request_id': request_id,
                            'user_id': user_id,
                            's3_bucket': s3_bucket,
                            's3_key': s3_key,
                            'etag': s3_etag,
                            'file_size': file_size,
                            'status': 'FAILED',
                            'error_message': str(e),
                            'created_at': timestamp,
                            'ttl': int(datetime.now(timezone.utc).timestamp()) + (30 * 24 * 60 * 60)
                        }
                    )
                    raise
            
            else:
                # File doesn't need Textract (TXT/CSV/MD)
                # Create DynamoDB record with SUCCEEDED status (ready for ingestion)
                print(f"File doesn't need Textract: {s3_key}")
                
                kb_jobs_table.put_item(
                    Item={
                        'job_id': request_id,  # Use request_id as job_id
                        'request_id': request_id,
                        'user_id': user_id,
                        's3_bucket': s3_bucket,
                        's3_key': s3_key,
                        'etag': s3_etag,
                        'file_size': file_size,
                        'status': 'SUCCEEDED',  # Ready for ingestion
                        'created_at': timestamp,
                        'ttl': int(datetime.now(timezone.utc).timestamp()) + (30 * 24 * 60 * 60)
                    }
                )
                
                print(f"Job record created (no Textract): {request_id}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Successfully processed file uploads',
                'environment': ENVIRONMENT
            })
        }
    
    except Exception as e:
        print(f"Error processing S3 event: {str(e)}")
        raise

