"""
KB Ingest Lambda Function
Triggered by SQS messages from Textract completion SNS topic.
- Parses SQS message to get JobId and S3 location
- Checks DynamoDB for idempotency (sns_message_id)
- Retrieves extracted text from Textract
- Cleans and deduplicates text (removes stopwords, URLs, emojis)
- Uploads raw text and cleaned terms to S3 kb_raw bucket
- Updates DynamoDB status to INGESTED
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Set
import boto3

# AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
textract_client = boto3.client('textract')
sns_client = boto3.client('sns')

# Environment variables
KB_JOBS_TABLE = os.environ['KB_JOBS_TABLE']
KB_RAW_BUCKET = os.environ['KB_RAW_BUCKET']
KB_TERMS_READY_TOPIC_ARN = os.environ.get('KB_TERMS_READY_TOPIC_ARN', '')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')

# DynamoDB table
kb_jobs_table = dynamodb.Table(KB_JOBS_TABLE)

# English stopwords (common words to exclude)
STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 
    'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 
    'by', 'can', 'did', 'do', 'does', 'doing', 'down', 'during', 'each', 'few', 'for', 'from', 
    'further', 'had', 'has', 'have', 'having', 'he', 'her', 'here', 'hers', 'herself', 'him', 
    'himself', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'itself', 'just', 
    'me', 'might', 'more', 'most', 'must', 'my', 'myself', 'no', 'nor', 'not', 'now', 'of', 
    'off', 'on', 'once', 'only', 'or', 'other', 'our', 'ours', 'ourselves', 'out', 'over', 
    'own', 's', 'same', 'she', 'should', 'so', 'some', 'such', 't', 'than', 'that', 'the', 
    'their', 'theirs', 'them', 'themselves', 'then', 'there', 'these', 'they', 'this', 'those', 
    'through', 'to', 'too', 'under', 'until', 'up', 'very', 'was', 'we', 'were', 'what', 
    'when', 'where', 'which', 'while', 'who', 'whom', 'why', 'will', 'with', 'would', 'you', 
    'your', 'yours', 'yourself', 'yourselves',
    
    # Common OCR / filler artifacts
    'page', 'pages', 'figure', 'fig', 'table', 'tables', 'etc', 'eg', 'ie', 'www', 'com',

    # Common numeric placeholders
    'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',

    # Noise tokens from scanned docs or metadata
    'copyright', 'rights', 'reserved', 'inc', 'ltd', 'corp', 'co', 'company', 'llc', 'isbn',
    'doi', 'vol', 'edition', 'chapter', 'section', 'article',

    # Extra high-frequency verbs and fillers
    'say', 'says', 'said', 'get', 'got', 'make', 'made', 'use', 'used', 'using', 'may', 'shall',
}


def is_url(text: str) -> bool:
    """Check if text is a URL."""
    url_pattern = r'^(https?://|www\.|ftp://)'
    return bool(re.match(url_pattern, text.lower()))


def is_email(text: str) -> bool:
    """Check if text is an email address."""
    email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return bool(re.match(email_pattern, text))


def clean_and_tokenize(text: str) -> Set[str]:
    """
    Clean text and extract unique tokens.
    
    Rules:
    - Split on non-alphanumerics (keep A-Z, 0-9, +, _, ., -)
    - Token length: 2-40 characters
    - Drop stopwords, URLs, emails
    - Convert to lowercase
    - Deduplicate
    
    Args:
        text: Raw text to process
        
    Returns:
        Set of unique cleaned tokens
    """
    if not text:
        return set()
    
    # Split on non-alphanumeric characters except +_.-
    # Keep these: [A-Za-z0-9+_.-]
    tokens = re.split(r'[^A-Za-z0-9+_.\-]+', text)
    
    cleaned_tokens = set()
    
    for token in tokens:
        if not token:  # Skip empty tokens
            continue
            
        # Convert to lowercase for consistency
        token_lower = token.lower()
        
        # Skip if too short or too long
        if len(token_lower) < 2 or len(token_lower) > 40:
            continue
        
        # Skip stopwords
        if token_lower in STOPWORDS:
            continue
        
        # Skip URLs
        if is_url(token_lower):
            continue
        
        # Skip emails
        if is_email(token_lower):
            continue
        
        # Skip tokens that are just punctuation
        if re.match(r'^[+_.\-]+$', token_lower):
            continue
        
        # Skip purely numeric strings (years, phone numbers, etc.)
        # Matches: "2017", "1000", "6084210314", "608-4210314", "608.421.0314"
        if re.match(r'^[\d+_.\-]+$', token_lower):
            continue
        
        # Skip tokens with emoji (basic check for non-ASCII)
        if not all(ord(c) < 128 for c in token_lower):
            continue
        
        cleaned_tokens.add(token_lower)
    
    return cleaned_tokens


def extract_text_from_textract(job_id: str) -> Dict[str, Any]:
    """
    Retrieve and extract all text from Textract job results.
    Handles pagination for large documents.
    """
    all_blocks = []
    next_token = None
    
    while True:
        if next_token:
            response = textract_client.get_document_analysis(
                JobId=job_id,
                NextToken=next_token
            )
        else:
            response = textract_client.get_document_analysis(JobId=job_id)
        
        all_blocks.extend(response.get('Blocks', []))
        
        next_token = response.get('NextToken')
        if not next_token:
            break
    
    # Extract text from LINE blocks
    lines = [block['Text'] for block in all_blocks if block['BlockType'] == 'LINE']
    
    # Extract tables (if any)
    tables = []
    for block in all_blocks:
        if block['BlockType'] == 'TABLE':
            tables.append({
                'id': block['Id'],
                'confidence': block.get('Confidence', 0)
            })
    
    return {
        'lines': lines,
        'full_text': '\n'.join(lines),
        'block_count': len(all_blocks),
        'line_count': len(lines),
        'table_count': len(tables),
        'document_metadata': response.get('DocumentMetadata', {})
    }


def lambda_handler(event, context):
    """
    Main Lambda handler for SQS messages from Textract completion.
    
    Flow:
    1. Parse SQS message to get SNS notification
    2. Extract JobId and S3 location from SNS message
    3. Check DynamoDB for idempotency using sns_message_id
    4. Retrieve text from Textract
    5. Upload to S3 kb_raw bucket
    6. Update DynamoDB status to INGESTED
    """
    print(f"Event: {json.dumps(event)}")
    
    processed_count = 0
    failed_count = 0
    
    try:
        # Process each SQS message
        for record in event['Records']:
            try:
                # Parse SNS message from SQS
                sns_message = json.loads(record['body'])
                message_id = sns_message['MessageId']
                
                # Parse Textract completion notification
                textract_message = json.loads(sns_message['Message'])
                job_id = textract_message['JobId']
                status = textract_message['Status']
                api = textract_message.get('API', 'Unknown')
                s3_bucket = textract_message['DocumentLocation']['S3Bucket']
                s3_key = textract_message['DocumentLocation']['S3ObjectName']
                
                print(f"Processing JobId: {job_id}, Status: {status}, File: s3://{s3_bucket}/{s3_key}")
                
                # Get job record from DynamoDB
                try:
                    db_response = kb_jobs_table.get_item(Key={'job_id': job_id})
                    if 'Item' not in db_response:
                        print(f"Warning: Job {job_id} not found in DynamoDB, skipping")
                        continue
                    
                    job_item = db_response['Item']
                    user_id = job_item['user_id']
                    
                    # Check idempotency - have we already processed this SNS message?
                    if job_item.get('sns_message_id') == message_id:
                        print(f"Already processed SNS message {message_id} for job {job_id}, skipping")
                        continue
                    
                    # Check if already ingested
                    if job_item.get('status') == 'INGESTED':
                        print(f"Job {job_id} already ingested, skipping")
                        continue
                    
                except Exception as e:
                    print(f"Error querying DynamoDB: {str(e)}")
                    failed_count += 1
                    continue
                
                # Only process SUCCEEDED jobs
                if status != 'SUCCEEDED':
                    print(f"Job {job_id} status is {status}, updating DynamoDB")
                    kb_jobs_table.update_item(
                        Key={'job_id': job_id},
                        UpdateExpression='SET #status = :status, sns_message_id = :msg_id, last_polled_at = :now',
                        ExpressionAttributeNames={'#status': 'status'},
                        ExpressionAttributeValues={
                            ':status': 'FAILED',
                            ':msg_id': message_id,
                            ':now': datetime.now(timezone.utc).isoformat()
                        }
                    )
                    failed_count += 1
                    continue
                
                # Extract text from Textract
                print(f"Extracting text from Textract job {job_id}")
                extracted_data = extract_text_from_textract(job_id)
                
                print(f"Extracted {extracted_data['line_count']} lines, {extracted_data['table_count']} tables")
                
                # Clean and tokenize text
                full_text = extracted_data['full_text']
                cleaned_terms = clean_and_tokenize(full_text)
                print(f"Cleaned: {len(cleaned_terms)} unique terms from {len(full_text.split())} raw words")
                
                # Prepare output filename
                # Original: user_id/document.pdf → Output: user_id/document.txt
                original_filename = os.path.basename(s3_key)
                base_name = os.path.splitext(original_filename)[0]
                output_key = f"{user_id}/{base_name}.txt"
                
                # Create metadata JSON
                metadata = {
                    'job_id': job_id,
                    'user_id': user_id,
                    'original_file': s3_key,
                    'processed_at': datetime.now(timezone.utc).isoformat(),
                    'api': api,
                    'line_count': extracted_data['line_count'],
                    'table_count': extracted_data['table_count'],
                    'block_count': extracted_data['block_count'],
                    'raw_word_count': len(full_text.split()),
                    'cleaned_term_count': len(cleaned_terms),
                    'document_metadata': extracted_data['document_metadata']
                }
                
                # Upload raw text to S3
                text_content = extracted_data['full_text']
                s3_client.put_object(
                    Bucket=KB_RAW_BUCKET,
                    Key=output_key,
                    Body=text_content.encode('utf-8'),
                    ContentType='text/plain',
                    Metadata={
                        'job-id': job_id,
                        'user-id': user_id,
                        'line-count': str(extracted_data['line_count']),
                        'term-count': str(len(cleaned_terms)),
                        'original-file': s3_key
                    }
                )
                
                print(f"Uploaded text to s3://{KB_RAW_BUCKET}/{output_key}")
                
                # Upload cleaned terms (deduplicated words)
                terms_key = f"{user_id}/{base_name}_terms.json"
                terms_data = {
                    'job_id': job_id,
                    'user_id': user_id,
                    'original_file': s3_key,
                    'term_count': len(cleaned_terms),
                    'terms': sorted(list(cleaned_terms))  # Sort for consistency
                }
                s3_client.put_object(
                    Bucket=KB_RAW_BUCKET,
                    Key=terms_key,
                    Body=json.dumps(terms_data, indent=2).encode('utf-8'),
                    ContentType='application/json',
                    Metadata={
                        'job-id': job_id,
                        'user-id': user_id,
                        'term-count': str(len(cleaned_terms))
                    }
                )
                
                print(f"Uploaded {len(cleaned_terms)} unique terms to s3://{KB_RAW_BUCKET}/{terms_key}")
                
                # Upload metadata JSON
                metadata_key = f"{user_id}/{base_name}_metadata.json"
                s3_client.put_object(
                    Bucket=KB_RAW_BUCKET,
                    Key=metadata_key,
                    Body=json.dumps(metadata, indent=2).encode('utf-8'),
                    ContentType='application/json'
                )
                
                print(f"Uploaded metadata to s3://{KB_RAW_BUCKET}/{metadata_key}")
                
                # Update DynamoDB status to INGESTED
                kb_jobs_table.update_item(
                    Key={'job_id': job_id},
                    UpdateExpression='SET #status = :status, sns_message_id = :msg_id, last_polled_at = :now, raw_text_s3_key = :s3_key',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':status': 'INGESTED',
                        ':msg_id': message_id,
                        ':now': datetime.now(timezone.utc).isoformat(),
                        ':s3_key': output_key
                    }
                )
                
                # Publish notification that terms are ready for alias generation
                if KB_TERMS_READY_TOPIC_ARN:
                    try:
                        sns_message = {
                            'job_id': job_id,
                            'user_id': user_id,
                            'terms_s3_key': terms_key,
                            'term_count': len(cleaned_terms),
                            'original_file': s3_key,
                            'processed_at': datetime.now(timezone.utc).isoformat()
                        }
                        
                        sns_client.publish(
                            TopicArn=KB_TERMS_READY_TOPIC_ARN,
                            Message=json.dumps(sns_message),
                            Subject=f'Terms ready for alias generation: {user_id}/{base_name}',
                            MessageAttributes={
                                'user_id': {'DataType': 'String', 'StringValue': user_id},
                                'job_id': {'DataType': 'String', 'StringValue': job_id},
                                'term_count': {'DataType': 'Number', 'StringValue': str(len(cleaned_terms))}
                            }
                        )
                        
                        print(f"✓ Published terms-ready notification to SNS for job {job_id}")
                    except Exception as sns_error:
                        print(f"Warning: Failed to publish SNS notification: {str(sns_error)}")
                        # Don't fail the whole job if SNS publish fails
                
                print(f"✓ Successfully processed job {job_id}")
                processed_count += 1
                
            except Exception as e:
                print(f"Error processing message: {str(e)}")
                failed_count += 1
                # Don't raise - let other messages in batch be processed
                continue
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Batch processing complete',
                'processed': processed_count,
                'failed': failed_count,
                'environment': ENVIRONMENT
            })
        }
    
    except Exception as e:
        print(f"Fatal error processing batch: {str(e)}")
        raise

