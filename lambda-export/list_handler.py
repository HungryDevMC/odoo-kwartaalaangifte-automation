# -*- coding: utf-8 -*-
"""List exports handler for S3 bucket contents."""

import json
import os
from datetime import datetime

import boto3


def lambda_handler(event: dict, context) -> dict:
    """List available exports in S3.

    Returns:
        List of export files with metadata
    """
    try:
        bucket = os.environ.get("S3_BUCKET")
        if not bucket:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "S3_BUCKET not configured"}),
            }

        s3 = boto3.client("s3")

        # List objects in exports/ prefix
        response = s3.list_objects_v2(
            Bucket=bucket,
            Prefix="exports/",
        )

        exports = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".zip"):
                filename = key.split("/")[-1]

                # Generate presigned URL
                download_url = s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=3600,
                )

                exports.append({
                    "filename": filename,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "download_url": download_url,
                })

        # Sort by date, newest first
        exports.sort(key=lambda x: x["last_modified"], reverse=True)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "exports": exports,
                "count": len(exports),
            }),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }

