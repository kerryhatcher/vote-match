"""Cloudflare R2 storage utilities for uploading generated maps."""

import logging
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from vote_match.config import Settings

logger = logging.getLogger(__name__)


def upload_to_r2(
    file_path: Path,
    object_key: str,
    settings: Settings,
    content_type: str = "text/html",
) -> str | None:
    """
    Upload a file to Cloudflare R2 storage.

    Args:
        file_path: Local file path to upload.
        object_key: Key (path) for the object in R2 bucket.
        settings: Application settings containing R2 configuration.
        content_type: MIME type of the file (default: text/html for maps).

    Returns:
        Public URL of the uploaded file if successful, None otherwise.

    Raises:
        ValueError: If R2 is not enabled or configuration is incomplete.
    """
    if not settings.r2_enabled:
        msg = "R2 upload is not enabled in configuration"
        raise ValueError(msg)

    # Validate required settings
    if not all(
        [
            settings.r2_endpoint_url,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
            settings.r2_bucket_name,
            settings.r2_public_url,
        ]
    ):
        msg = "R2 configuration is incomplete. Check .env settings."
        raise ValueError(msg)

    logger.info(f"Uploading {file_path} to R2 bucket {settings.r2_bucket_name} as {object_key}")

    try:
        # Create S3 client configured for Cloudflare R2
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",  # R2 uses "auto" for region
        )

        # Upload file
        with open(file_path, "rb") as f:
            s3_client.upload_fileobj(
                f,
                settings.r2_bucket_name,
                object_key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": "public, max-age=3600",  # Cache for 1 hour
                },
            )

        # Construct public URL
        public_url = f"{settings.r2_public_url.rstrip('/')}/{object_key}"

        logger.info(f"Successfully uploaded to R2: {public_url}")

        return public_url

    except (BotoCoreError, ClientError) as e:
        logger.error(f"Failed to upload to R2: {e}")
        return None
