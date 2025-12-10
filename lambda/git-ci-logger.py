import json
import os
import logging
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Set up logging configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)


# --- Configuration ---
# Get table name from environment variable, default to 'github-ci-history'
DYNAMODB_TABLE_NAME = os.environ.get("TABLE_NAME", "github-ci-history") 
REGION_NAME = os.environ.get("AWS_REGION", "us-east-1")
SQS_QUEUE_NAME = "nlp-for-devops-sqs" # SQS Queue Name
lambda_client = boto3.client('lambda', region_name=REGION_NAME)
# ---------------------


# Initialize AWS clients
try:
    # DynamoDB Resource for simplified put_item
    dynamodb = boto3.resource("dynamodb", region_name=REGION_NAME)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    # SQS Client for manual polling
    sqs = boto3.client("sqs", region_name=REGION_NAME)
except Exception as e:
    logger.error(f"Failed to initialize AWS clients: {e}")
    raise


# --- DynamoDB Helper Function (unchanged) ---
def put_item_to_dynamodb(item):
    """
    Executes the put_item operation to store the item in the DynamoDB table.
    ...
    """
    build_id = item.get('build-id', 'N/A')
    try:
        table.put_item(
            Item=item
        )
        logger.info(f"Successfully put item with build-id: {build_id}")
    except ClientError as e:
        logger.error(f"DynamoDB Client Error for build-id {build_id}: {e.response['Error']['Message']}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during put_item for build-id {build_id}: {e}")
        raise

# --- Image Tag Helper Function (unchanged) ---
def extract_full_image_tag(repo_url, version):
    """
    Extracts the repository path (e.g., 'user/repo') and appends the version tag.
    ...
    """
    try:
        parts = repo_url.rstrip('/').split('/')
        
        if len(parts) >= 2:
            repo_path = f"{parts[-2]}/{parts[-1]}"
            full_image_tag = f"{repo_path}:{version}"
            return full_image_tag
        else:
            logger.warning(f"Could not parse repo_url: {repo_url}")
            return f"N/A:{version}"
            
    except Exception as e:
        logger.error(f"Error during image tag extraction: {e}")
        return f"N/A:{version}"

# --- Core Processing Logic (Extracted from lambda_handler) ---
def process_single_message_data(message_data, message_id):
    """
    Handles the business logic: extracts data from the SQS message, 
    generates necessary keys, inserts the item into DynamoDB, and 
    triggers the EKS deployment Lambda function asynchronously.
    """
    # DEBUG 1: Log the keys present in the incoming SQS message body for troubleshooting.
    logger.info(f"Input message_data keys: {list(message_data.keys())}") 

    # 1. Extract core fields from the parsed SQS message body
    repo_url = message_data.get('repo_url')
    version = message_data.get('version', 'latest') 
    
    # *** CRITICAL FIX POINT ***
    # Ensure the environment value from the SQS message is used. 
    # If the 'environment' key is missing, default to 'prod' as the fallback namespace.
    current_environment = message_data.get('environment', 'prod') 
    
    # 2. Derive the full image tag (e.g., 'user/repo:tag')
    full_image_tag = extract_full_image_tag(repo_url, version)
    
    # 3. Generate Primary Key (PK) and Sort Key
    build_id = str(uuid.uuid4())  # Generate a unique ID for the build record
    timestamp_str = datetime.now(timezone.utc).isoformat()  # Capture the current time in ISO format
    
    # 4. Construct the DynamoDB Item
    item = {
        'build-id': build_id, 
        'timestamp': timestamp_str, 
        'full_image_tag': full_image_tag,
        
        # Fields extracted directly from SQS message
        'repo_url': repo_url,
        'version': version,
        'environment': current_environment, # Use the determined environment variable (e.g., 'QA' or 'prod')
        'lex_session_id': message_data.get('lex_session_id', 'N/A'),
        'bot_id': message_data.get('bot_id', 'N/A'),
        'bot_alias_id': message_data.get('bot_alias_id', 'N/A'),
        'originating_request_id': message_data.get('originating_request_id', 'N/A'),
        
        # SQS message metadata
        'sqs_message_id': message_id
    }
    
    # DEBUG 2: Check the environment value that will be persisted to DynamoDB.
    logger.info(f"DynamoDB Environment value: {item['environment']}") 

    # 5. Call the encapsulated function to put the item (Persist data)
    put_item_to_dynamodb(item)
    
    # 6. Lambda Invocation Setup
    namespace_to_deploy = current_environment # Use the validated environment as the target namespace

    # Construct the payload for the EKS deployment Lambda function
    payload = {
        "action": "apply", # The EKS Lambda action to perform (e.g., 'apply' YAML files)
        "image": full_image_tag, # The full image tag to use in the deployment file replacement
        "namespace": namespace_to_deploy 
    }
    
    # DEBUG 3: Check the namespace being passed to the EKS deployment Lambda.
    logger.info(f"EKS Invocation Payload Namespace: {namespace_to_deploy}") 

    # 7. Invoke the EKS Deployment Lambda asynchronously
    try:
        lambda_client.invoke(
            FunctionName="nlp-for-devops-eks-prod", # Target EKS deployment Lambda function
            InvocationType='Event',                  # Asynchronous invocation (non-blocking)
            Payload=json.dumps(payload)
        )
        logger.info(f"Successfully triggered EKS Lambda for {full_image_tag} in namespace {namespace_to_deploy}")
    except Exception as e:
        logger.error(f"Failed to trigger EKS Lambda: {e}")
        # Re-raise the exception to ensure the SQS message is NOT deleted if the critical downstream action fails.
        raise

# --- Manual Polling Function (For Testing) ---
def poll_and_process_sqs_message():
    """
    Manually polls one message from the SQS queue and triggers processing.
    This simulates the environment of a non-triggered Lambda or a local test.
    """
    logger.info("-" * 50)
    logger.info(f"Attempting to poll one message from {SQS_QUEUE_NAME}...")
    
    try:
        # 1. Get the Queue URL
        response = sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)
        queue_url = response['QueueUrl']
        print(f"Queue URL: {queue_url}")

        # 2. Poll the message
        messages_response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=5 # Use Long Polling
        )

        # 3. Check if a message was received
        if 'Messages' in messages_response:
            message = messages_response['Messages'][0]
            
            receipt_handle = message['ReceiptHandle']
            message_id = message['MessageId']
            message_body = message['Body']
            
            logger.info(f"Received Message ID: {message_id}")
            
            # --- Processing Logic ---
            try:
                # 3a. Parse the message body
                message_data = json.loads(message_body)
                
                # 3b. Call the separated business logic
                process_single_message_data(message_data, message_id)
                
                # 3c. If processing succeeds, delete the message
                sqs.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt_handle
                )
                logger.info(f"Successfully processed and deleted message {message_id}.")
                return True
                
            except Exception as e:
                logger.error(f"Processing failed for message {message_id}. Message will remain in queue: {e}")
                # Note: Do NOT delete the message here so SQS can handle Visibility Timeout/DLQ.
                return False
        
        else:
            logger.info("No messages received after waiting.")
            return None

    except ClientError as e:
        logger.error(f"SQS Client Error during polling: {e.response['Error']['Message']}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during polling: {e}")
        return False


# --- Lambda Handler (Simplified for Event Source Mapping) ---
def lambda_handler(event, context):
    """
    The original Lambda handler, now simplified to iterate through records
    and call the processing logic directly (assuming SQS Event Source Mapping).
    """
    if 'Records' not in event:
        logger.warning("Event does not contain SQS records.")
        return {'statusCode': 200, 'body': json.dumps('No records to process')}
        
    print(f"Received {len(event['Records'])} messages from SQS.")

    for record in event['Records']:
        message_id = record.get('messageId', 'unknown')
        sqs_message_body = record['body']
        
        try:
            message_data = json.loads(sqs_message_body)
            # Call the core logic
            process_single_message_data(message_data, message_id)
        
        except json.JSONDecodeError:
            # Errors logged in process_single_message_data and its helpers will trigger a re-raise
            raise
        except ClientError:
            # Errors logged in process_single_message_data and its helpers will trigger a re-raise
            raise
        except Exception:
            # Ensures all errors are propagated for SQS to handle
            raise

    return {
        'statusCode': 200,
        'body': json.dumps('All messages processed successfully')
    }
