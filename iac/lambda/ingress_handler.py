import json
import boto3
import os
import time
import base64
from datetime import datetime

# Initialize AWS clients
kinesis_client = boto3.client('kinesis')
dynamodb = boto3.resource('dynamodb')

# Get environment variables
LANDMARKS_STREAM_NAME = os.environ.get('LANDMARKS_STREAM_NAME', 'asl-landmarks-stream')
CONNECTIONS_TABLE_NAME = os.environ.get('CONNECTIONS_TABLE_NAME', 'asl-websocket-connections')

# DynamoDB table
connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)

def lambda_handler(event, context):
    """
    Lambda handler for WebSocket API Gateway events (INGRESS ONLY).
    
    Architecture:
    - This is ONE-WAY ingress: client → API GW → Lambda → Kinesis
    - Lambda returns statusCode to API Gateway (not sent to client)
    - For OUTBOUND (server → client), use separate Outbound Lambda with API GW Management API
    
    Routes messages to appropriate handlers based on route key.
    """
    
    route_key = event.get('requestContext', {}).get('routeKey')
    connection_id = event.get('requestContext', {}).get('connectionId')
    
    print(f"Route: {route_key}, ConnectionId: {connection_id}")
    
    # Handle different WebSocket routes
    if route_key == '$connect':
        return handle_connect(event)
    elif route_key == '$disconnect':
        return handle_disconnect(event)
    elif route_key == '$default' or route_key == 'sendlandmarks':
        return handle_landmarks(event)
    else:
        return {
            'statusCode': 400,
            'body': json.dumps({'message': f'Unsupported route: {route_key}'})
        }

def handle_connect(event):
    """
    Handle WebSocket connection event.
    Store connectionId in DynamoDB (session_id will be added later when first message arrives).
    """
    connection_id = event.get('requestContext', {}).get('connectionId')
    print(f"New connection: {connection_id}")
    
    try:
        # Store connection in DynamoDB with placeholder session_id
        connections_table.put_item(
            Item={
                'connectionId': connection_id,
                'session_id': 'pending',  # Will be updated when first message arrives
                'connected_at': datetime.utcnow().isoformat(),
                'ttl': int(time.time()) + 86400  # 24 hour TTL
            }
        )
        print(f"Stored connection {connection_id} in DynamoDB")
    except Exception as e:
        print(f"Error storing connection in DynamoDB: {str(e)}")
        # Don't fail the connection if DynamoDB fails
    
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Connected'})
    }

def handle_disconnect(event):
    """
    Handle WebSocket disconnection event.
    Remove connectionId from DynamoDB.
    """
    connection_id = event.get('requestContext', {}).get('connectionId')
    print(f"Disconnection: {connection_id}")
    
    try:
        # Remove connection from DynamoDB
        connections_table.delete_item(
            Key={'connectionId': connection_id}
        )
        print(f"Removed connection {connection_id} from DynamoDB")
    except Exception as e:
        print(f"Error removing connection from DynamoDB: {str(e)}")
        # Don't fail the disconnection if DynamoDB fails
    
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Disconnected'})
    }

def handle_landmarks(event):
    """
    Handle landmark data and write to Kinesis stream.
    
    IMPORTANT: This is ONE-WAY ingress. The Lambda returns statusCode to API Gateway,
    but NO response is sent back to the WebSocket client. For downstream communication
    (server → client), use a separate Outbound Lambda with API Gateway Management API.
    """
    try:
        connection_id = event.get('requestContext', {}).get('connectionId')
        
        # Parse the message body
        body = event.get('body', '{}')
        if isinstance(body, str):
            message_data = json.loads(body)
        else:
            message_data = body
        
        # Extract session_id (use connection_id if not provided)
        session_id = message_data.get('session_id', connection_id)
        
        # Extract landmark data
        landmarks = message_data.get('data', [])
        
        if not landmarks:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No landmark data provided'})
            }
        
        # Update DynamoDB with session_id mapping (for future outbound Lambda use)
        try:
            connections_table.update_item(
                Key={'connectionId': connection_id},
                UpdateExpression='SET session_id = :sid, last_activity = :ts',
                ExpressionAttributeValues={
                    ':sid': session_id,
                    ':ts': datetime.utcnow().isoformat()
                }
            )
            print(f"Updated DynamoDB: {connection_id} ↔ {session_id}")
        except Exception as e:
            print(f"Warning: Failed to update DynamoDB: {str(e)}")
            # Continue processing even if DynamoDB update fails
        
        # Prepare record for Kinesis
        kinesis_record = {
            'session_id': session_id,
            'connection_id': connection_id,
            'timestamp': datetime.utcnow().isoformat(),
            'landmarks': landmarks,
            'metadata': {
                'source': 'websocket',
                'event_time': event.get('requestContext', {}).get('requestTimeEpoch')
            }
        }
        
        # Write to Kinesis stream
        response = kinesis_client.put_record(
            StreamName=LANDMARKS_STREAM_NAME,
            Data=json.dumps(kinesis_record),
            PartitionKey=session_id
        )
        
        print(f"Successfully wrote to Kinesis: ShardId={response['ShardId']}, SequenceNumber={response['SequenceNumber']}")
        
        # Return 200 to API Gateway (NOT sent to client in WebSocket AWS_PROXY mode)
        return {
            'statusCode': 200
        }
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        return {
            'statusCode': 400
        }
    except Exception as e:
        print(f"Error processing landmarks: {str(e)}")
        return {
            'statusCode': 500
        }

