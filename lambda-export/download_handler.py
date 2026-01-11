# -*- coding: utf-8 -*-
"""Download handler for presigned S3 URLs."""

import json
import os

import boto3


def lambda_handler(event: dict, context) -> dict:
    """Generate presigned URL for downloading an export.

    Args:
        event: API Gateway event with filename in path parameters
        context: Lambda context

    Returns:
        Redirect to presigned URL or error
    """
    try:
        # Get filename from path
        filename = event.get("pathParameters", {}).get("filename")
        if not filename:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing filename"}),
            }

        bucket = os.environ.get("S3_BUCKET")
        if not bucket:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "S3_BUCKET not configured"}),
            }

        # Generate presigned URL
        s3 = boto3.client("s3")
        s3_key = f"exports/{filename}"

        # Check if file exists
        try:
            s3.head_object(Bucket=bucket, Key=s3_key)
        except s3.exceptions.ClientError:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": f"File not found: {filename}"}),
            }

        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=3600,  # 1 hour
        )

        # Redirect to the presigned URL
        return {
            "statusCode": 302,
            "headers": {
                "Location": presigned_url,
            },
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }

