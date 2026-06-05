# Storing call recordings in AWS S3

By default Twilio stores call recordings in Twilio's cloud and Odoo plays them from
there. You can instead store recordings in your own AWS S3 bucket and control how long
they are kept. This keeps the media under your control and removes Twilio storage costs.

How it works: Twilio uploads each new recording directly to your S3 bucket; Odoo reads
and plays it back from S3. Recordings created before you switch stay on Twilio and keep
working (mixed mode).

> **Note (voice):** Twilio has **no API** to enable external storage for *voice*
> recordings — the final enable step is done once in the Twilio Console. Odoo automates
> everything else (bucket creation, the Twilio AWS credential, the ready-to-paste URL).

---

## 1. AWS — create one IAM user

Create a single IAM user (programmatic access) and attach this least-privilege policy.
It lets Odoo create/configure the bucket and read recordings, and lets Twilio write them.
No `iam:*` permissions are granted, so the key is not an admin key. The bucket-name prefix
(`oduist-connect-*`) limits which buckets the key can touch. Odoo adds this prefix to your
bucket name automatically, so you only enter a suffix (e.g. `recordings-acme`).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateAndConfigureBucket",
      "Effect": "Allow",
      "Action": ["s3:CreateBucket", "s3:PutBucketPublicAccessBlock",
                 "s3:PutEncryptionConfiguration", "s3:PutLifecycleConfiguration",
                 "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::oduist-connect-*"
    },
    {
      "Sid": "ReadWriteObjects",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket",
                 "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts",
                 "s3:ListBucketMultipartUploads"],
      "Resource": ["arn:aws:s3:::oduist-connect-*",
                   "arn:aws:s3:::oduist-connect-*/*"]
    }
  ]
}
```

Generate an **Access Key ID** + **Secret Access Key** for this user (use case
"Application running outside AWS"). The choice of use case does not change the key.

## 2. Odoo — Connect Settings → S3 Storage

1. Enter the **AWS Access Key ID** and **AWS Secret Access Key**.
2. Pick the **AWS Region** (e.g. `eu-central-1` for EU/GDPR). The region is permanent for
   the bucket.
3. Enter an **S3 Bucket Name** suffix (globally unique, e.g. `recordings-<yourcompany>`).
   Odoo prepends the `oduist-connect-` prefix automatically to match the IAM policy. Also
   set a **Folder (prefix)** (default `recordings`).
4. Set **Retention (days)** — `0` keeps recordings forever; `N` deletes the audio file
   after N days (the recording row and its transcript are kept; the player shows
   "Recording expired").
5. Click **Create / configure S3 bucket** — Odoo creates the bucket, blocks public access,
   enables encryption, and applies the retention lifecycle rule.
6. Click **Create Twilio AWS credential** — Odoo registers your AWS key with Twilio and
   stores the resulting credential SID (`CR…`). You do **not** paste AWS keys into Twilio.

## 3. Twilio Console — enable external storage (one time)

1. Twilio Console → **Voice → Recordings → Settings**.
2. Enable **external S3 storage**.
3. Select the AWS credential **connect-s3-recordings** (the SID shown in Odoo).
4. Paste the **S3 URL** shown in Odoo (the read-only "S3 URL (paste into Twilio)" field).
5. **Save**.

## 4. Odoo — turn it on

Tick **Store recordings in S3** in Connect Settings → S3 Storage.

## 5. Verify

Make a short recorded call. Confirm a new object appears under `recordings/` in your
bucket, and the recording plays back inside Odoo. Old (pre-switch) recordings still play
from Twilio.

## Retention

Retention is enforced by an S3 lifecycle rule on the bucket. After N days AWS deletes the
audio object; Odoo keeps the recording record (and transcript/summary) and shows
"Recording expired" in the player. Change the period by updating **Retention (days)** and
clicking **Create / configure S3 bucket** again.
