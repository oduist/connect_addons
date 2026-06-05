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

The prefix is configurable in **Connect Settings → S3 Storage → S3 Bucket Prefix**
(default `oduist-connect-`); set your own to match an existing IAM naming convention. The
policy shown on that page is generated from the prefix you choose, so it always matches —
copy it straight from there instead of the static example below.

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

Step by step in the AWS Console:

1. **IAM → Users → Create user** — give it a name (e.g. `connect-s3`).
2. On **Set permissions**, choose **Attach policies directly → Create policy → JSON**,
   paste the policy above, name it (e.g. `connect-s3-recordings`), create it and attach it
   to the user.
3. Open the user → **Security credentials → Create access key** → *Application running
   outside AWS* → copy the **Access Key ID** and **Secret access key**.

(The same policy and these steps are shown directly in Odoo on the S3 Storage settings
page, generated from your chosen prefix — copy them from there.)

## 2. Odoo — Connect Settings → S3 Storage

First tick **Store recordings in S3** — this reveals the S3 settings below. Then:

1. Keep the default **S3 Bucket Prefix** (`oduist-connect-`) or set your own; the IAM
   policy shown updates to match. Copy that policy and attach it to the IAM user (section 1).
2. Enter the **AWS Access Key ID** and **AWS Secret Access Key**.
3. Pick the **AWS Region** (e.g. `eu-central-1` for EU/GDPR). The region is permanent for
   the bucket.
4. Enter an **S3 Bucket Name** suffix (globally unique, e.g. `recordings-<yourcompany>`).
   Odoo prepends the bucket prefix automatically to match the IAM policy. Also set a
   **Folder (prefix)** (default `recordings`).
5. Set **Retention (days)** — `0` keeps recordings forever; `N` deletes the audio file
   after N days (the recording row and its transcript are kept; the player shows
   "Recording expired").
6. Click **Create / configure S3 bucket** — Odoo creates the bucket, blocks public access,
   enables encryption, and applies the retention lifecycle rule.
7. Click **Create Twilio AWS credential** — Odoo registers your AWS key with Twilio and
   stores the resulting credential SID (`CR…`). You do **not** paste AWS keys into Twilio.

## 3. Twilio Console — enable external storage (one time)

1. Twilio Console → **Voice → Recordings → Settings**.
2. Enable **external S3 storage**.
3. Select the AWS credential **connect-s3-recordings** (the SID shown in Odoo).
4. Paste the **S3 URL** shown in Odoo (the read-only "S3 URL (paste into Twilio)" field).
5. **Save**.

## 4. Odoo — it's already on

**Store recordings in S3** was switched on in step 2 to reveal the settings, so there is
nothing more to toggle. Recordings that Twilio uploads to your bucket are now read from
S3; older (pre-switch) recordings keep playing from Twilio.

## 5. Verify

Make a short recorded call. Confirm a new object appears under `recordings/` in your
bucket, and the recording plays back inside Odoo. Old (pre-switch) recordings still play
from Twilio.

## Retention

Retention is enforced by an S3 lifecycle rule on the bucket. After N days AWS deletes the
audio object; Odoo keeps the recording record (and transcript/summary) and shows
"Recording expired" in the player. Change the period by updating **Retention (days)** and
clicking **Create / configure S3 bucket** again.
