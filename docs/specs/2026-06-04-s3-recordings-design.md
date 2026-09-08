# S3 storage for call recordings — design (ODU-36)

- **Ticket:** ODU-36 / GitHub oduist/connect_addons#117
- **Module:** `connect`
- **Status:** approved design, ready for implementation plan
- **Date:** 2026-06-04

## Problem

Twilio call recordings are currently stored in Twilio's cloud and referenced from
`connect.recording.media_url`. We want to store recordings in a customer-owned AWS S3
bucket and expose S3 storage options (retention) in Connect settings, so the customer
owns the media lifecycle and avoids Twilio storage charges.

## Research conclusions (must respect)

- **Variant B confirmed by docs:** once Twilio external S3 storage is enabled, media can
  no longer be fetched from Twilio — `media_url` / `RecordingUrl` point to the S3 location.
  Therefore Odoo must read media directly from S3 → **boto3 is required** (new dependency).
- **Twilio VOICE external-S3 enable is Console-only.** There is no public REST API for
  voice recording settings (Twilio's OpenAPI spec has `RecordingSettings` only for *video*;
  docs/blog describe only Console: **Voice → Recordings → Settings**). Odoo cannot flip the
  toggle programmatically; the admin does it once in the Console.
- **What Odoo CAN automate (validated live):**
  - create + configure the S3 bucket via boto3 (block-public, SSE-S3, lifecycle);
  - create the Twilio AWS Credential via `POST https://accounts.twilio.com/v1/Credentials/AWS`
    (`Credentials=ACCESSKEY:SECRET`, `FriendlyName`) → returns a `CR…` SID, so the admin does
    not paste AWS keys into the Console.

## Scope

In scope:
1. AWS/S3 config + credentials in `connect.settings`.
2. Buttons to auto-provision the bucket (boto3) and the Twilio AWS credential (API).
3. In-app ready-to-copy values (S3 URL, credential SID) + step-by-step Twilio Console
   instructions, plus a repo markdown setup guide.
4. Read/playback + transcription from S3 (variant B) with mixed-mode (old recordings stay
   on Twilio).
5. Retention via S3 lifecycle + an "expired" indicator on recordings.

Out of scope (YAGNI):
- SSE-KMS (use SSE-S3).
- Migrating existing Twilio-hosted recordings into S3 (mixed-mode handles old ones).
- Auto-flipping the Twilio voice Console toggle (impossible for voice).

## Architecture

### 1. Settings model (`connect.settings`)
New fields (secrets follow the existing `field` + `display_field` + `groups=` pattern):

- `s3_recordings_enabled` (Boolean) — master flag for the feature in Odoo (drives read path + UI).
- `aws_access_key_id` (Char)
- `aws_secret_access_key` (Char, `groups="base.group_erp_manager"`) + `display_aws_secret_access_key` (masked)
- `aws_region` (Selection of common regions, **required**, default `eu-central-1`)
- `aws_s3_bucket` (Char; default suggestion `oduist-connect-recordings-<dbuuid>`)
- `aws_s3_prefix` (Char, default `recordings`)
- `s3_retention_days` (Integer, default `0` = keep forever; `>0` sets a lifecycle rule)
- `aws_s3_url` (Char, compute, readonly) — ready-to-paste: `https://{bucket}.s3.{region}.amazonaws.com/{prefix}`
- `twilio_aws_credential_sid` (Char, readonly) — `CR…` after creation

### 2. Provisioning actions
- `action_provision_s3_bucket()` — boto3: `create_bucket(region)` → `put_public_access_block`
  → `put_bucket_encryption` (SSE-S3) → `put_bucket_lifecycle_configuration` (only if
  `s3_retention_days > 0`). Idempotent (tolerate `BucketAlreadyOwnedByYou`).
- `action_create_twilio_aws_credential()` — `POST accounts.twilio.com/v1/Credentials/AWS`,
  store the returned `CR…` SID. Idempotent (look up existing by `FriendlyName`).
- `_get_s3_client()` — boto3 client built from settings creds + region.

### 3. Read / playback (variant B, mixed-mode)
- URL detector: is `media_url` our S3 (`*.amazonaws.com` + our bucket) vs Twilio (`api.twilio.com`)?
- `_serve_media` (`connect/controllers/main.py`): S3 → stream via boto3 `get_object`;
  Twilio → current path (`requests` + `account_sid`/`auth_token`).
- `_get_recording_widget` (`connect/models/recording.py`):
  - `proxy_recordings=True` (default) → `/connect/recording/<id>` (Odoo streams via boto3);
  - `proxy_recordings=False` → presigned S3 URL (boto3 `generate_presigned_url`).
- `transcribe_recording` — download S3 media via boto3 to a temp file instead of `requests.get`.

### 4. Retention + "expired"
- Lifecycle rule set during provisioning from `s3_retention_days` (Expiration Days).
- Computed `recording_expired` from `start_time + retention_days` vs now (no S3 call); the
  widget shows "Recording expired". The recording row (transcript/summary) is **kept**.
- Safety net: on read, catch `NoSuchKey` → treat as expired.

### 5. Instruction (in-app + repo doc)
- In-app S3 section on the settings page: status, `aws_s3_url` (copy button),
  `twilio_aws_credential_sid`, a numbered Twilio Console checklist (Voice → Recordings →
  Settings → enable → pick credential → paste URL → Save), and a collapsible IAM policy JSON
  for creating the least-privilege IAM user.
- Repo doc: `connect/docs/s3-recordings-setup.md` — AWS steps (IAM user + policy JSON),
  Odoo steps (enter keys → Setup), Twilio Console steps.

### 6. Dependencies & security
- Add `boto3` to `connect/__manifest__.py` `external_dependencies.python` and to
  `requirements.txt` (boto3 line already present uncommitted).
- AWS secret under `group_erp_manager` + masked display; bucket private; least-privilege IAM
  policy (create/configure bucket scoped to a name prefix; `PutObject`/multipart for Twilio
  write; `GetObject`/`ListBucket` for Odoo read; add `GetLifecycleConfiguration`, optional
  `DeleteObject`).

## IAM policy (admin creates one IAM user with this)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateAndConfigureBucket",
      "Effect": "Allow",
      "Action": ["s3:CreateBucket", "s3:PutBucketPublicAccessBlock",
                 "s3:PutEncryptionConfiguration", "s3:PutLifecycleConfiguration",
                 "s3:GetLifecycleConfiguration", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::oduist-connect-recordings-*"
    },
    {
      "Sid": "ReadWriteObjects",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:DeleteObject",
                 "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts",
                 "s3:ListBucketMultipartUploads"],
      "Resource": ["arn:aws:s3:::oduist-connect-recordings-*",
                   "arn:aws:s3:::oduist-connect-recordings-*/*"]
    }
  ]
}
```

## Testing

- Unit: S3-vs-Twilio URL detector; `aws_s3_url` compute; lifecycle param building;
  `recording_expired` compute.
- Live (deferred): place a recorded call with external storage on → confirm object lands in
  the bucket → confirm exact `media_url` / S3-key format → verify proxy stream + presigned +
  transcription.

## Open item

The exact `media_url` / S3-key format Twilio writes is **not yet confirmed live** (the test
account toggle did not take effect during research). The read path (section 3) must use a
**flexible key parser** derived from the observed URL once the live test succeeds.

## Test environment facts

- Twilio "Development" account `AC6b97…`; AWS account `361738333006`, IAM user `connect`.
- Live test bucket `oduist-connect-recordings-eu-361738333006` (eu-central-1); Twilio
  credential `CR84ee4b1ea7a3911e39e4b882f0a303a1`.
- The `connect` IAM user currently lacks `s3:DeleteObject`/`DeleteBucket`/`GetLifecycleConfiguration`
  — add to the final policy.
- AWS creds in `connect_addons/19.0/.env`; Twilio creds in `/Users/poligon/Workspace/manage/.env`
  (use `account_sid` + `display_auth_token`; the `display_*` API secret is masked/401).
