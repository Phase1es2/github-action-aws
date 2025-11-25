import json
import os
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("TABLE_NAME", "github-ci-history")
table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """
    Expected JSON event from GitHub Actions:
    {
      "repository": "Phase1es2/github-action-aws",
      "actor": "majiny",
      "branch": "master",
      "commit": "abc1234",
      "version": "250125-1.0.0-abc1234",
      "docker_image": "majiny/django-app:250125-1.0.0-abc1234",
      "ci_status": "success",
      "timestamp": "2025-11-25T21:30:00Z"
    }
    """

    logger.info("Received event: %s", json.dumps(event))

    timestamp = event.get("timestamp")
    if not timestamp:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    build_id = f"{timestamp}-{event.get('commit', 'unknown')[:7]}"

    item = {
        "build-id": build_id,
        "timestamp": timestamp,
        "repository": event.get("repository", "unknown"),
        "actor": event.get("actor", "unknown"),
        "branch": event.get("branch", "unknown"),
        "commit": event.get("commit", "unknown"),
        "version": event.get("version", "unknown"),
        "dockerImage": event.get("docker_image", "unknown"),
        "ciStatus": event.get("ci_status", "unknown")
    }

    try:
        table.put_item(Item=item)
        logger.info("Item added to DynamoDB: %s", item)
    except ClientError as e:
        logger.error("Error writing to DynamoDB: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps("Error writing to DynamoDB")
        }

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "OK", "build_id": build_id})
    }