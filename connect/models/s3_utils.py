# -*- coding: utf-8 -*-
"""Pure helpers for S3 recording storage.

No Odoo or boto3 imports here on purpose: keep this unit-testable in isolation.
"""
import json
from urllib.parse import urlparse
from datetime import timedelta


# Bucket names are auto-prefixed so they stay inside the IAM policy's allowed
# ARN (arn:aws:s3:::oduist-connect-*). Keep this in sync with that policy.
S3_BUCKET_PREFIX = "oduist-connect-"


def normalize_bucket_name(name, prefix=S3_BUCKET_PREFIX):
    """Ensure the bucket name starts with `prefix` (idempotent).

    Blank stays blank. A name already starting with the prefix is returned
    unchanged; otherwise the prefix is prepended. The user only needs to type a
    suffix (e.g. "recordings-acme" -> "oduist-connect-recordings-acme").
    """
    name = (name or "").strip()
    if not name:
        return name
    return name if name.startswith(prefix) else prefix + name


def build_iam_policy(prefix=S3_BUCKET_PREFIX):
    """Return the least-privilege AWS IAM policy (pretty JSON) for the S3 key.

    Bucket ARNs are derived from `prefix`, so the policy always matches the
    auto-prefixed bucket names. Attach it to the IAM user whose access key is
    entered in Connect Settings; it grants only bucket create/configure and
    object read/write under the prefix, no `iam:*`.
    """
    bucket_arn = "arn:aws:s3:::{}*".format(prefix)
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CreateAndConfigureBucket",
                "Effect": "Allow",
                "Action": [
                    "s3:CreateBucket",
                    "s3:PutBucketPublicAccessBlock",
                    "s3:PutEncryptionConfiguration",
                    "s3:PutLifecycleConfiguration",
                    "s3:GetBucketLocation",
                ],
                "Resource": bucket_arn,
            },
            {
                "Sid": "ReadWriteObjects",
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:ListBucket",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                    "s3:ListBucketMultipartUploads",
                ],
                "Resource": [bucket_arn, bucket_arn + "/*"],
            },
        ],
    }
    return json.dumps(policy, indent=2)


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
