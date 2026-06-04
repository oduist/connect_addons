# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
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

    def test_recording_expired_flag(self):
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
