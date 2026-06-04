# -*- coding: utf-8 -*-
"""Pure helpers for S3 recording storage.

No Odoo or boto3 imports here on purpose: keep this unit-testable in isolation.
"""
from urllib.parse import urlparse
from datetime import timedelta


def build_s3_url(bucket, region, prefix):
    """Return the Twilio-ready https URL for a bucket+prefix (no trailing slash)."""
    prefix = (prefix or "").strip("/")
    base = "https://{}.s3.{}.amazonaws.com".format(bucket, region)
    return "{}/{}".format(base, prefix) if prefix else base


def is_s3_media_url(media_url, bucket):
    """True if media_url points at our S3 bucket (any AWS S3 host style)."""
    if not media_url or not bucket:
        return False
    host = urlparse(media_url).hostname or ""
    return host.endswith("amazonaws.com") and bucket in media_url


def parse_s3_key(media_url, bucket):
    """Extract the S3 object key from a full https S3 URL.

    Handles virtual-hosted ("bucket.s3...amazonaws.com/key") and
    path-style ("s3...amazonaws.com/bucket/key").
    """
    parsed = urlparse(media_url)
    host = parsed.hostname or ""
    path = (parsed.path or "").lstrip("/")
    if host.startswith("{}.".format(bucket)):
        return path
    if path.startswith("{}/".format(bucket)):
        return path[len(bucket) + 1:]
    return path


def build_lifecycle_config(prefix, days):
    """S3 lifecycle config that expires objects under prefix after `days`."""
    prefix = (prefix or "").strip("/")
    return {
        "Rules": [{
            "ID": "connect-recordings-retention",
            "Filter": {"Prefix": "{}/".format(prefix) if prefix else ""},
            "Status": "Enabled",
            "Expiration": {"Days": int(days)},
        }]
    }


def is_recording_expired(start_time, retention_days, now):
    """True if a recording's S3 object has passed its lifecycle expiry."""
    if not retention_days or not start_time:
        return False
    return now >= start_time + timedelta(days=int(retention_days))
