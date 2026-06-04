# -*- coding: utf-8 -*-
import unittest
from datetime import datetime
from odoo.addons.connect.models import s3_utils


class TestS3Utils(unittest.TestCase):
    # ---- build_s3_url ----
    def test_build_s3_url_with_prefix(self):
        url = s3_utils.build_s3_url("my-bucket", "eu-central-1", "recordings")
        self.assertEqual(url, "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings")

    def test_build_s3_url_strips_slashes(self):
        url = s3_utils.build_s3_url("my-bucket", "eu-central-1", "/recordings/")
        self.assertEqual(url, "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings")

    def test_build_s3_url_no_prefix(self):
        url = s3_utils.build_s3_url("my-bucket", "us-east-1", "")
        self.assertEqual(url, "https://my-bucket.s3.us-east-1.amazonaws.com")

    # ---- is_s3_media_url ----
    def test_is_s3_media_url_true_virtual_hosted(self):
        url = "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings/AC1/RE1"
        self.assertTrue(s3_utils.is_s3_media_url(url, "my-bucket"))

    def test_is_s3_media_url_false_for_twilio(self):
        url = "https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE1"
        self.assertFalse(s3_utils.is_s3_media_url(url, "my-bucket"))

    def test_is_s3_media_url_false_when_empty(self):
        self.assertFalse(s3_utils.is_s3_media_url("", "my-bucket"))

    # ---- parse_s3_key ----
    def test_parse_s3_key_virtual_hosted(self):
        url = "https://my-bucket.s3.eu-central-1.amazonaws.com/recordings/AC1/RE1.mp3"
        self.assertEqual(s3_utils.parse_s3_key(url, "my-bucket"), "recordings/AC1/RE1.mp3")

    def test_parse_s3_key_path_style(self):
        url = "https://s3.eu-central-1.amazonaws.com/my-bucket/recordings/RE1.mp3"
        self.assertEqual(s3_utils.parse_s3_key(url, "my-bucket"), "recordings/RE1.mp3")

    # ---- build_lifecycle_config ----
    def test_build_lifecycle_config(self):
        cfg = s3_utils.build_lifecycle_config("recordings", 30)
        rule = cfg["Rules"][0]
        self.assertEqual(rule["Status"], "Enabled")
        self.assertEqual(rule["Expiration"], {"Days": 30})
        self.assertEqual(rule["Filter"], {"Prefix": "recordings/"})
        self.assertEqual(rule["ID"], "connect-recordings-retention")

    # ---- is_recording_expired ----
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
