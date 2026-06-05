# S3 Storage for Call Recordings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store Twilio call recordings in a customer-owned AWS S3 bucket, with retention and in-app setup guidance, while keeping playback/transcription working (variant B) and old Twilio-hosted recordings still playable (mixed-mode).

**Architecture:** All pure logic (URL build/parse, lifecycle config, expiry) lives in a dependency-free `connect/models/s3_utils.py` so it is unit-testable without AWS/Twilio. The `connect.settings` model gains S3 config fields + provisioning actions (boto3 + Twilio Credentials API). `connect.recording` and the recording controller branch on the media URL host to read from S3 (boto3) or Twilio (existing path). Twilio's voice external-storage toggle stays a one-time manual Console step (no API exists); Odoo surfaces a ready-to-copy URL + instructions.

**Tech Stack:** Odoo 19 (Python), boto3 (new dep), Twilio REST (`accounts.twilio.com/v1/Credentials/AWS`), Odoo QWeb views.

**Spec:** `docs/superpowers/specs/2026-06-04-s3-recordings-design.md`

**Conventions:**
- Commit messages: `[connect] <lowercase imperative subject>` (square brackets; no `feat/fix/chore`).
- Tests are Odoo tests run via the oduflow `run_odoo_tests` MCP tool (or CLI: `odoo -d <db> -u connect --test-enable --test-tags /connect --stop-after-init`). Pure-logic tests live in `connect/tests/test_s3_utils.py` and import `odoo.addons.connect.models.s3_utils` (no DB needed, but run through the Odoo runner).
- After Python changes: restart the container AND upgrade `connect` before manual retest (see memory: `--dev` does not reload Python).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `requirements.txt` | declare boto3 for the dev env | Modify (boto3 line already present, uncommitted) |
| `connect/__manifest__.py` | declare boto3 as external python dep | Modify |
| `connect/models/s3_utils.py` | pure helpers: build URL, detect/parse S3 key, lifecycle config, expiry | Create |
| `connect/models/settings.py` | S3 config fields, `aws_s3_url` compute, `_get_s3_client`, provisioning actions | Modify |
| `connect/models/recording.py` | `recording_expired` field, S3 branch in widget + transcription | Modify |
| `connect/controllers/main.py` | `_serve_media` S3 branch | Modify |
| `connect/views/settings.xml` | S3 settings section: fields, ready URL, Console instructions | Modify |
| `connect/docs/s3-recordings-setup.md` | end-to-end AWS+Twilio setup guide | Create |
| `connect/tests/test_s3_utils.py` | unit tests for `s3_utils` | Create |
| `connect/tests/__init__.py` | register the new test module | Modify/Create |

---

## Task 1: Declare boto3 dependency

**Files:**
- Modify: `requirements.txt` (boto3 line already added, uncommitted)
- Modify: `connect/__manifest__.py:17-19`

- [ ] **Step 1: Add boto3 to the manifest external deps**

In `connect/__manifest__.py`, change:
```python
    "external_dependencies": {
        "python": ["twilio", "openai", "PyJWT"],
    },
```
to:
```python
    "external_dependencies": {
        "python": ["twilio", "openai", "PyJWT", "boto3"],
    },
```

- [ ] **Step 2: Verify boto3 import resolves in the env**

Run (oduflow): `run_odoo_command` with `python -c "import boto3; print(boto3.__version__)"`, or locally `uv run --with boto3 python -c "import boto3; print(boto3.__version__)"`.
Expected: a version string, no ImportError.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt connect/__manifest__.py
git commit -m "[connect] add boto3 dependency for S3 recording storage"
```

---

## Task 2: `build_s3_url` (pure)

**Files:**
- Create: `connect/models/s3_utils.py`
- Create: `connect/tests/test_s3_utils.py`
- Modify: `connect/tests/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `connect/tests/test_s3_utils.py`:
```python
import unittest
from odoo.addons.connect.models import s3_utils


class TestS3Utils(unittest.TestCase):
    def test_build_s3_url_with_prefix(self):
        url = s3_utils.build_s3_url("my-bucket", "eu-central-1", "recordings")
        self.assertEqual(url, "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings")

    def test_build_s3_url_strips_slashes(self):
        url = s3_utils.build_s3_url("my-bucket", "eu-central-1", "/recordings/")
        self.assertEqual(url, "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings")

    def test_build_s3_url_no_prefix(self):
        url = s3_utils.build_s3_url("my-bucket", "us-east-1", "")
        self.assertEqual(url, "https://my-bucket.s3.us-east-1.amazonaws.com")
```

Ensure `connect/tests/__init__.py` imports it (append):
```python
from . import test_s3_utils
```
(If `connect/tests/__init__.py` does not exist, create it with just that line. Also confirm `connect/__manifest__.py` / module loads the `tests` package — Odoo auto-discovers `tests/`.)

- [ ] **Step 2: Run test, verify it fails**

Run (oduflow `run_odoo_tests`, tags `/connect:TestS3Utils`) or CLI:
`odoo -d <db> -u connect --test-enable --test-tags /connect:TestS3Utils --stop-after-init`
Expected: FAIL — `ModuleNotFoundError: ... s3_utils` (file not created yet).

- [ ] **Step 3: Create the module with the function**

Create `connect/models/s3_utils.py`:
```python
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
```

- [ ] **Step 4: Run test, verify it passes**

Run the same command as Step 2. Expected: PASS (3 assertions in `test_build_s3_url_*`).

- [ ] **Step 5: Commit**

```bash
git add connect/models/s3_utils.py connect/tests/test_s3_utils.py connect/tests/__init__.py
git commit -m "[connect] add s3_utils.build_s3_url helper"
```

---

## Task 3: `is_s3_media_url` + `parse_s3_key` (pure)

**Files:**
- Modify: `connect/models/s3_utils.py`
- Modify: `connect/tests/test_s3_utils.py`

> Rationale: the exact Twilio external-storage `media_url` layout is unconfirmed (spec "Open item"). We make detection/parse **format-agnostic** — work off the URL host + path — so the layout does not matter. Task 16 confirms live.

- [ ] **Step 1: Add failing tests**

Append to `TestS3Utils` in `connect/tests/test_s3_utils.py`:
```python
    def test_is_s3_media_url_true_virtual_hosted(self):
        url = "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings/AC1/RE1"
        self.assertTrue(s3_utils.is_s3_media_url(url, "my-bucket"))

    def test_is_s3_media_url_false_for_twilio(self):
        url = "https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE1"
        self.assertFalse(s3_utils.is_s3_media_url(url, "my-bucket"))

    def test_is_s3_media_url_false_when_empty(self):
        self.assertFalse(s3_utils.is_s3_media_url("", "my-bucket"))

    def test_parse_s3_key_virtual_hosted(self):
        url = "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings/AC1/RE1.mp3"
        self.assertEqual(s3_utils.parse_s3_key(url, "my-bucket"), "recordings/AC1/RE1.mp3")

    def test_parse_s3_key_path_style(self):
        url = "https://s3.eu-central-1.amazonaws.com/my-bucket/recordings/RE1.mp3"
        self.assertEqual(s3_utils.parse_s3_key(url, "my-bucket"), "recordings/RE1.mp3")
```

- [ ] **Step 2: Run, verify fail**

Run tags `/connect:TestS3Utils`. Expected: FAIL — `AttributeError: module ... has no attribute 'is_s3_media_url'`.

- [ ] **Step 3: Implement**

Append to `connect/models/s3_utils.py`:
```python
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
```

- [ ] **Step 4: Run, verify pass**

Run tags `/connect:TestS3Utils`. Expected: PASS (all assertions).

- [ ] **Step 5: Commit**

```bash
git add connect/models/s3_utils.py connect/tests/test_s3_utils.py
git commit -m "[connect] add s3_utils S3 URL detection and key parsing"
```

---

## Task 4: `build_lifecycle_config` (pure)

**Files:**
- Modify: `connect/models/s3_utils.py`
- Modify: `connect/tests/test_s3_utils.py`

- [ ] **Step 1: Add failing test**

Append to `TestS3Utils`:
```python
    def test_build_lifecycle_config(self):
        cfg = s3_utils.build_lifecycle_config("recordings", 30)
        rule = cfg["Rules"][0]
        self.assertEqual(rule["Status"], "Enabled")
        self.assertEqual(rule["Expiration"], {"Days": 30})
        self.assertEqual(rule["Filter"], {"Prefix": "recordings/"})
        self.assertEqual(rule["ID"], "connect-recordings-retention")
```

- [ ] **Step 2: Run, verify fail** — tags `/connect:TestS3Utils`. Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement** — append to `s3_utils.py`:
```python
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
```

- [ ] **Step 4: Run, verify pass** — tags `/connect:TestS3Utils`. Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add connect/models/s3_utils.py connect/tests/test_s3_utils.py
git commit -m "[connect] add s3_utils.build_lifecycle_config helper"
```

---

## Task 5: `is_recording_expired` (pure)

**Files:**
- Modify: `connect/models/s3_utils.py`
- Modify: `connect/tests/test_s3_utils.py`

- [ ] **Step 1: Add failing test**

Append to `TestS3Utils` (add `from datetime import datetime, timedelta` at top of test file):
```python
    def test_recording_not_expired_when_retention_zero(self):
        self.assertFalse(s3_utils.is_recording_expired(datetime(2020, 1, 1), 0, datetime(2030, 1, 1)))

    def test_recording_not_expired_when_no_start(self):
        self.assertFalse(s3_utils.is_recording_expired(None, 30, datetime(2030, 1, 1)))

    def test_recording_expired_after_window(self):
        start = datetime(2026, 1, 1)
        self.assertTrue(s3_utils.is_recording_expired(start, 30, datetime(2026, 3, 1)))

    def test_recording_not_expired_within_window(self):
        start = datetime(2026, 1, 1)
        self.assertFalse(s3_utils.is_recording_expired(start, 30, datetime(2026, 1, 10)))
```

- [ ] **Step 2: Run, verify fail** — tags `/connect:TestS3Utils`. Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement** — append to `s3_utils.py`:
```python
def is_recording_expired(start_time, retention_days, now):
    """True if a recording's S3 object has passed its lifecycle expiry."""
    if not retention_days or not start_time:
        return False
    return now >= start_time + timedelta(days=int(retention_days))
```

- [ ] **Step 4: Run, verify pass** — tags `/connect:TestS3Utils`. Expected: PASS (all `TestS3Utils`).

- [ ] **Step 5: Commit**
```bash
git add connect/models/s3_utils.py connect/tests/test_s3_utils.py
git commit -m "[connect] add s3_utils.is_recording_expired helper"
```

---

## Task 6: Settings — S3 config fields + `aws_s3_url` compute

**Files:**
- Modify: `connect/models/settings.py` (fields near `:270`, the RECORDING section; import near top)
- Modify: `connect/tests/test_s3_utils.py` (add a small TransactionCase for the compute) — or new `connect/tests/test_s3_settings.py`

- [ ] **Step 1: Add the import**

Near the top of `connect/models/settings.py`, add:
```python
from . import s3_utils
```

- [ ] **Step 2: Add fields**

Inside the `RECORDING & TRANSCRIPT FIELDS` block (after `proxy_recordings`, around `connect/models/settings.py:273`), add:
```python
    # ---- S3 recording storage (ODU-36) ----
    s3_recordings_enabled = fields.Boolean(
        string="Store recordings in S3",
        help="Read recordings from your AWS S3 bucket instead of Twilio. "
             "Enable AFTER configuring external storage in the Twilio Console.",
    )
    aws_access_key_id = fields.Char(string="AWS Access Key ID")
    aws_secret_access_key = fields.Char(
        string="AWS Secret Access Key", groups="base.group_erp_manager"
    )
    display_aws_secret_access_key = fields.Char(string="AWS Secret Access Key")
    aws_region = fields.Selection(
        selection=[
            ("eu-central-1", "EU (Frankfurt)"),
            ("eu-west-1", "EU (Ireland)"),
            ("us-east-1", "US East (N. Virginia)"),
            ("us-west-2", "US West (Oregon)"),
            ("ap-southeast-1", "Asia Pacific (Singapore)"),
        ],
        string="AWS Region", default="eu-central-1", required=True,
    )
    aws_s3_bucket = fields.Char(string="S3 Bucket Name")
    aws_s3_prefix = fields.Char(string="S3 Folder (prefix)", default="recordings")
    s3_retention_days = fields.Integer(
        string="Retention (days)", default=0,
        help="0 = keep forever. >0 sets an S3 lifecycle rule that deletes the audio "
             "file after N days (the recording row and transcript are kept).",
    )
    aws_s3_url = fields.Char(
        string="S3 URL (paste into Twilio)", compute="_compute_aws_s3_url", readonly=True,
    )
    twilio_aws_credential_sid = fields.Char(
        string="Twilio AWS Credential SID", readonly=True,
    )
```

- [ ] **Step 3: Add the compute method**

Add to the `Settings` class (e.g. after `_get_name`):
```python
    @api.depends("aws_s3_bucket", "aws_region", "aws_s3_prefix")
    def _compute_aws_s3_url(self):
        for rec in self:
            if rec.aws_s3_bucket and rec.aws_region:
                rec.aws_s3_url = s3_utils.build_s3_url(
                    rec.aws_s3_bucket, rec.aws_region, rec.aws_s3_prefix
                )
            else:
                rec.aws_s3_url = False
```

- [ ] **Step 4: Add a compute test**

Create `connect/tests/test_s3_settings.py`:
```python
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestS3Settings(TransactionCase):
    def test_aws_s3_url_compute(self):
        s = self.env["connect.settings"].create({
            "aws_s3_bucket": "my-bucket",
            "aws_region": "eu-central-1",
            "aws_s3_prefix": "recordings",
        })
        self.assertEqual(
            s.aws_s3_url,
            "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings",
        )

    def test_aws_s3_url_empty_without_bucket(self):
        s = self.env["connect.settings"].create({"aws_region": "us-east-1"})
        self.assertFalse(s.aws_s3_url)
```
Append to `connect/tests/__init__.py`:
```python
from . import test_s3_settings
```

- [ ] **Step 5: Run, verify pass**

Run tags `/connect:TestS3Settings`. Expected: PASS. (Restart + `-u connect` so the new fields load.)

- [ ] **Step 6: Commit**
```bash
git add connect/models/settings.py connect/tests/test_s3_settings.py connect/tests/__init__.py
git commit -m "[connect] add S3 settings fields and aws_s3_url compute"
```

---

## Task 7: Settings — `_get_s3_client` helper

**Files:**
- Modify: `connect/models/settings.py`

- [ ] **Step 1: Implement helper**

Add to the `Settings` class:
```python
    def _get_s3_client(self):
        """boto3 S3 client built from the singleton settings record."""
        import boto3
        rec = self if self else self.search([], limit=1)
        rec = rec[0]
        return boto3.client(
            "s3",
            aws_access_key_id=rec.aws_access_key_id,
            aws_secret_access_key=rec.aws_secret_access_key,
            region_name=rec.aws_region,
        )
```

- [ ] **Step 2: Smoke-check against the test account**

Run (oduflow `run_odoo_shell`, single call):
```python
s = env["connect.settings"].search([], limit=1)
s.write({
    "aws_access_key_id": "<from connect_addons/19.0/.env>",
    "aws_secret_access_key": "<from .env>",
    "aws_region": "eu-central-1",
})
client = s._get_s3_client()
print(client.list_buckets()["Owner"]["ID"])
```
Expected: prints an owner ID (creds valid). Do NOT commit secrets.

- [ ] **Step 3: Commit**
```bash
git add connect/models/settings.py
git commit -m "[connect] add _get_s3_client helper on connect.settings"
```

---

## Task 8: Settings — `action_provision_s3_bucket`

**Files:**
- Modify: `connect/models/settings.py`

> Integration code (hits AWS). Verified manually against the test account, not by unit test.

- [ ] **Step 1: Implement the action**

Add to the `Settings` class:
```python
    def action_provision_s3_bucket(self):
        from botocore.exceptions import ClientError
        self.ensure_one()
        if not (self.aws_s3_bucket and self.aws_region):
            raise ValidationError("Set S3 bucket name and region first.")
        s3 = self._get_s3_client()
        bucket = self.aws_s3_bucket
        # create_bucket: us-east-1 must NOT send LocationConstraint
        try:
            if self.aws_region == "us-east-1":
                s3.create_bucket(Bucket=bucket)
            else:
                s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": self.aws_region},
                )
        except ClientError as e:
            if e.response["Error"]["Code"] not in (
                "BucketAlreadyOwnedByYou", "BucketAlreadyExists"
            ):
                raise ValidationError("S3 create_bucket failed: %s" % e)
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )
        s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )
        if self.s3_retention_days and self.s3_retention_days > 0:
            s3.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration=s3_utils.build_lifecycle_config(
                    self.aws_s3_prefix, self.s3_retention_days
                ),
            )
        self.env["connect.settings"].connect_notify(
            "S3 bucket '%s' provisioned." % bucket, notify_uid=self.env.uid
        )
        return True
```
Confirm `ValidationError` is imported in `settings.py` (it is used elsewhere; if not, add `from odoo.exceptions import ValidationError`).

- [ ] **Step 2: Manual verification**

In the settings form (after Task 14) or via `run_odoo_shell`: set bucket=`oduist-connect-recordings-eu-<acct>`, region=`eu-central-1`, retention=30, call `action_provision_s3_bucket()`. Then confirm via boto3 `list_objects_v2`/`get_bucket_encryption` that the bucket exists, is private, encrypted, and has the lifecycle rule.
Expected: no exception; bucket configured.

- [ ] **Step 3: Commit**
```bash
git add connect/models/settings.py
git commit -m "[connect] add action_provision_s3_bucket"
```

---

## Task 9: Settings — `action_create_twilio_aws_credential`

**Files:**
- Modify: `connect/models/settings.py`

- [ ] **Step 1: Implement the action**

Ensure `import requests` exists in `settings.py` (add if missing). Add to the `Settings` class:
```python
    def action_create_twilio_aws_credential(self):
        self.ensure_one()
        if not (self.aws_access_key_id and self.aws_secret_access_key):
            raise ValidationError("Set AWS access key and secret first.")
        sid = self.account_sid
        token = self.auth_token or self.display_auth_token
        friendly = "connect-s3-recordings"
        base = "https://accounts.twilio.com/v1/Credentials/AWS"
        # idempotent: reuse existing credential with our FriendlyName
        existing = requests.get(base, auth=(sid, token), timeout=30)
        existing.raise_for_status()
        for cred in existing.json().get("credentials", []):
            if cred.get("friendly_name") == friendly:
                self.twilio_aws_credential_sid = cred["sid"]
                return True
        resp = requests.post(
            base, auth=(sid, token), timeout=30,
            data={
                "Credentials": "%s:%s" % (self.aws_access_key_id, self.aws_secret_access_key),
                "FriendlyName": friendly,
            },
        )
        resp.raise_for_status()
        self.twilio_aws_credential_sid = resp.json()["sid"]
        self.env["connect.settings"].connect_notify(
            "Twilio AWS credential created: %s" % self.twilio_aws_credential_sid,
            notify_uid=self.env.uid,
        )
        return True
```

- [ ] **Step 2: Manual verification**

Via the form/shell, call `action_create_twilio_aws_credential()` with the test-account creds. Confirm a `CR…` SID is stored, and calling it twice does not create a duplicate (idempotent).
Expected: `twilio_aws_credential_sid` set to a `CR…` value; second call returns the same SID.

- [ ] **Step 3: Commit**
```bash
git add connect/models/settings.py
git commit -m "[connect] add action_create_twilio_aws_credential"
```

---

## Task 10: Recording — `recording_expired` field

**Files:**
- Modify: `connect/models/recording.py` (import + field + compute)
- Modify: `connect/tests/test_s3_settings.py` (add expiry test)

- [ ] **Step 1: Add failing test**

Append to `TestS3Settings` in `connect/tests/test_s3_settings.py`:
```python
    def test_recording_expired_flag(self):
        from datetime import datetime, timedelta
        self.env["connect.settings"].search([], limit=1).write({"s3_retention_days": 30})
        old = self.env["connect.recording"].create({
            "sid": "REtest_old", "call_sid": "CAtest",
            "start_time": datetime.now() - timedelta(days=40),
        })
        fresh = self.env["connect.recording"].create({
            "sid": "REtest_new", "call_sid": "CAtest",
            "start_time": datetime.now() - timedelta(days=1),
        })
        self.assertTrue(old.recording_expired)
        self.assertFalse(fresh.recording_expired)
```

- [ ] **Step 2: Run, verify fail** — tags `/connect:TestS3Settings`. Expected: FAIL (`recording_expired` does not exist).

- [ ] **Step 3: Implement**

In `connect/models/recording.py`, add the import near the top:
```python
from . import s3_utils
```
Add the field (near the other fields, e.g. after `status` at `connect/models/recording.py:40`):
```python
    recording_expired = fields.Boolean(compute="_compute_recording_expired")
```
Add the compute method to the `Recording` class:
```python
    def _compute_recording_expired(self):
        days = self.env["connect.settings"].sudo().get_param("s3_retention_days")
        now = fields.Datetime.now()
        for rec in self:
            rec.recording_expired = s3_utils.is_recording_expired(rec.start_time, days, now)
```

- [ ] **Step 4: Run, verify pass** — tags `/connect:TestS3Settings`. Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add connect/models/recording.py connect/tests/test_s3_settings.py
git commit -m "[connect] add recording_expired computed flag"
```

---

## Task 11: Recording — S3 branch in `_get_recording_widget`

**Files:**
- Modify: `connect/models/recording.py:191-205`

- [ ] **Step 1: Implement the S3/expired/presigned branch**

Replace `_get_recording_widget` (`connect/models/recording.py:191`) with:
```python
    def _get_recording_widget(self):
        settings = self.env["connect.settings"].sudo()
        proxy_recordings = settings.get_param("proxy_recordings")
        s3_enabled = settings.get_param("s3_recordings_enabled")
        bucket = settings.get_param("aws_s3_bucket")
        for rec in self:
            if not rec.media_url:
                rec.recording_widget = ""
                continue
            if rec.recording_expired:
                rec.recording_widget = "<i>Recording expired</i>"
                continue
            is_s3 = s3_enabled and s3_utils.is_s3_media_url(rec.media_url, bucket)
            if proxy_recordings:
                media_url = "/connect/recording/{}".format(rec.id)
            elif is_s3:
                media_url = settings._get_s3_client().generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": s3_utils.parse_s3_key(rec.media_url, bucket)},
                    ExpiresIn=3600,
                )
            else:
                media_url = rec.media_url
            rec.recording_widget = (
                '<audio id="sound_file" preload="auto" controls="controls"> '
                '<source src="{}"/></audio>'.format(media_url)
            )
```

- [ ] **Step 2: Manual verification**

With `proxy_recordings=False` and `s3_recordings_enabled=True` on a recording whose `media_url` is an S3 URL, open the recording form and confirm the audio widget `src` is a presigned `...amazonaws.com/...X-Amz-Signature...` URL. With `proxy_recordings=True`, confirm it is `/connect/recording/<id>`.
Expected: correct `src` per mode; expired recordings show "Recording expired".

- [ ] **Step 3: Commit**
```bash
git add connect/models/recording.py
git commit -m "[connect] serve S3 recordings via proxy or presigned URL"
```

---

## Task 12: Recording — transcription reads from S3

**Files:**
- Modify: `connect/models/recording.py:76-91` (the `requests.get(self.media_url, ...)` block in `transcribe_recording`)

- [ ] **Step 1: Implement S3 download branch**

In `transcribe_recording`, replace the download block:
```python
            response = requests.get(self.media_url, stream=True)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                temp_file_path = temp_file.name
```
with:
```python
            settings = self.env["connect.settings"].sudo()
            bucket = settings.get_param("aws_s3_bucket")
            if settings.get_param("s3_recordings_enabled") and s3_utils.is_s3_media_url(self.media_url, bucket):
                key = s3_utils.parse_s3_key(self.media_url, bucket)
                with NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                    settings._get_s3_client().download_fileobj(bucket, key, temp_file)
                    temp_file_path = temp_file.name
            else:
                response = requests.get(self.media_url, stream=True)
                response.raise_for_status()
                with NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            temp_file.write(chunk)
                    temp_file_path = temp_file.name
```

- [ ] **Step 2: Manual verification**

On an S3-hosted recording with `transcript_calls=True` and a valid OpenAI key, trigger `get_transcript()`; confirm a transcript is produced (download came from S3, no Twilio 404).
Expected: transcript populated; no error.

- [ ] **Step 3: Commit**
```bash
git add connect/models/recording.py
git commit -m "[connect] download recording media from S3 for transcription"
```

---

## Task 13: Controller — `_serve_media` S3 branch

**Files:**
- Modify: `connect/controllers/main.py:55-66`

- [ ] **Step 1: Implement**

Add the import at the top of `connect/controllers/main.py`:
```python
from odoo.addons.connect.models import s3_utils
```
Replace `_serve_media` (`connect/controllers/main.py:55`) with:
```python
    def _serve_media(self, media_url):
        settings = http.request.env["connect.settings"].sudo()
        bucket = settings.get_param("aws_s3_bucket")
        if settings.get_param("s3_recordings_enabled") and s3_utils.is_s3_media_url(media_url, bucket):
            key = s3_utils.parse_s3_key(media_url, bucket)
            s3 = settings._get_s3_client()
            try:
                obj = s3.get_object(Bucket=bucket, Key=key)
            except s3.exceptions.NoSuchKey:
                return http.Response(status=410)  # gone (lifecycle-expired)
            data = obj["Body"].read()
            res = http.Response(data, content_type=obj.get("ContentType") or "audio/mpeg")
            res.headers["Content-Disposition"] = http.content_disposition(key.split("/")[-1])
            return res
        media_name = "{}.wav".format(media_url.split("/")[-1])
        account_sid = settings.get_param("account_sid")
        auth_token = settings.get_param("auth_token")
        response = requests.get(media_url, auth=(account_sid, auth_token))
        if response.status_code == 200:
            res = http.Response(response.content, content_type="audio/wav")
            res.headers["Content-Disposition"] = http.content_disposition(media_name)
            return res
        raise UserError("Failed to download the media. Status code: %s" % response.status_code)
```

- [ ] **Step 2: Manual verification**

With `proxy_recordings=True`, `s3_recordings_enabled=True`, open `/connect/recording/<id>` for an S3 recording in the browser; confirm audio plays (200, served by Odoo from S3). For an expired key, confirm HTTP 410. For an old Twilio recording, confirm the legacy path still works.
Expected: S3 stream OK; expired → 410; Twilio legacy → OK.

- [ ] **Step 3: Commit**
```bash
git add connect/controllers/main.py
git commit -m "[connect] stream S3 recordings from _serve_media controller"
```

---

## Task 14: Settings view — S3 section + ready URL + instructions

**Files:**
- Modify: `connect/views/settings.xml`

- [ ] **Step 1: Add the S3 group to the settings form**

Find the recording/transcript area of the form in `connect/views/settings.xml` and add a new group/page (match the file's existing structure — `notebook`/`page` vs `group`). Insert:
```xml
<group string="S3 Recording Storage" name="s3_storage">
    <field name="s3_recordings_enabled"/>
    <field name="aws_access_key_id"/>
    <field name="display_aws_secret_access_key" password="True"/>
    <field name="aws_region"/>
    <field name="aws_s3_bucket"/>
    <field name="aws_s3_prefix"/>
    <field name="s3_retention_days"/>
    <button name="action_provision_s3_bucket" type="object"
            string="Create / configure S3 bucket" class="btn-primary"/>
    <button name="action_create_twilio_aws_credential" type="object"
            string="Create Twilio AWS credential"/>
    <field name="twilio_aws_credential_sid" readonly="1"/>
    <field name="aws_s3_url" readonly="1"
           help="Copy this into the Twilio Console S3 URL field."/>
    <div colspan="2" class="text-muted">
        <p><b>Final step (Twilio Console — voice has no API):</b></p>
        <ol>
            <li>Twilio Console → Voice → Recordings → Settings.</li>
            <li>Enable external S3 storage.</li>
            <li>Pick AWS credential <i>connect-s3-recordings</i> (SID shown above).</li>
            <li>Paste the S3 URL shown above.</li>
            <li>Save. New recordings now go to your bucket.</li>
        </ol>
    </div>
</group>
```
Note: follow the secret-field convention used for `display_twilio_api_secret` in this view (the `display_*` field is what is shown/edited; wire the real `aws_secret_access_key` from `display_aws_secret_access_key` on write the same way the module already syncs other `display_*` secrets — replicate that existing onchange/write logic for the new pair).

- [ ] **Step 2: Verify the form renders**

Restart + `-u connect`, open Connect Settings. Confirm the S3 group renders, the secret field is masked, buttons appear, and `aws_s3_url` updates live when bucket/region/prefix change.
Expected: section renders; no view validation error in logs.

- [ ] **Step 3: Commit**
```bash
git add connect/views/settings.xml connect/models/settings.py
git commit -m "[connect] add S3 storage section to Connect settings view"
```

---

## Task 15: Repo setup guide

**Files:**
- Create: `connect/docs/s3-recordings-setup.md`

- [ ] **Step 1: Write the guide**

Create `connect/docs/s3-recordings-setup.md` covering, in order:
1. **AWS**: create one IAM user; attach the least-privilege policy (paste the JSON from the spec); generate an access key.
2. **Odoo**: Connect Settings → S3 Recording Storage → enter access key/secret + region + bucket name + retention → click **Create / configure S3 bucket** → click **Create Twilio AWS credential**.
3. **Twilio Console** (voice has no API): Voice → Recordings → Settings → enable external storage → pick credential `connect-s3-recordings` → paste the **S3 URL** shown in Odoo → Save.
4. **Enable in Odoo**: tick **Store recordings in S3**.
5. **Verify**: make a recorded call; confirm the object appears under `recordings/` in the bucket and plays back in Odoo.
6. **Retention note**: lifecycle deletes the audio after N days; the recording row + transcript are kept and the player shows "Recording expired".

Include the IAM policy JSON verbatim from `docs/superpowers/specs/2026-06-04-s3-recordings-design.md`.

- [ ] **Step 2: Commit**
```bash
git add connect/docs/s3-recordings-setup.md
git commit -m "[connect] add S3 recordings setup guide"
```

---

## Task 16: Live end-to-end verification (deferred — resolves spec Open item)

**Files:** none (verification + possible follow-up fix to `parse_s3_key`)

- [ ] **Step 1: Enable + call**

Ensure Twilio Console external storage is ON for the test project (account `AC6b97…`), credential `connect-s3-recordings`, S3 URL = the bucket URL. Make one recorded call.

- [ ] **Step 2: Confirm S3 write + capture format**

Run `run_odoo_shell` / boto3 `list_objects_v2` on the bucket → confirm a new object under `recordings/`. Fetch the new `connect.recording.media_url` and record its exact host + path.

- [ ] **Step 3: Confirm parser**

Check `s3_utils.parse_s3_key(media_url, bucket)` returns exactly the object key observed in Step 2. If the layout differs from the assumption, adjust `parse_s3_key` (and its tests in Task 3) accordingly, then re-run `/connect:TestS3Utils`.

- [ ] **Step 4: Confirm playback + transcription + expiry**

Verify: proxy playback (`/connect/recording/<id>` → 200), presigned mode, transcription on the S3 file, and (set retention small / delete the object) the "Recording expired" path → 410.

- [ ] **Step 5: Commit any parser fix**
```bash
git add connect/models/s3_utils.py connect/tests/test_s3_utils.py
git commit -m "[connect] align S3 key parser with live Twilio media_url format"
```

---

## Self-Review (done at write time)

- **Spec coverage:** settings fields (T6), provisioning bucket (T8) + Twilio credential (T9), read path proxy/presigned (T11) + controller (T13) + transcription (T12), retention lifecycle (T8) + expired marker (T10/T11/T13), in-app instructions + ready URL (T14), repo guide (T15), boto3 dep (T1), mixed-mode (host detection in T3 used everywhere). Open item → T16. All spec sections mapped.
- **Type/name consistency:** `s3_utils.build_s3_url / is_s3_media_url / parse_s3_key / build_lifecycle_config / is_recording_expired`; settings fields `aws_*`, `s3_recordings_enabled`, `aws_s3_url`, `twilio_aws_credential_sid`; methods `_get_s3_client`, `action_provision_s3_bucket`, `action_create_twilio_aws_credential`; recording `recording_expired` — used identically across tasks.
- **Placeholders:** none — every code step shows full code; the only deferred unknown (Twilio media_url layout) is explicitly handled by a format-agnostic parser + T16.
