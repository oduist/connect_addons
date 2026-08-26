from datetime import date, timedelta

from markupsafe import Markup

from odoo.tests import tagged

from .common import MemoryCommon


@tagged("post_install", "-at_install")
class TestBackfill(MemoryCommon):
    """Historical correspondence replay: the per-partner form action and the
    all-partners wizard/cron job. Both enqueue directly and are idempotent."""

    def _historical_message(self):
        """Post a customer message while capture is OFF, so only the backfill
        path (not live capture) enqueues it."""
        settings = self.env["connect.settings"].sudo()
        settings.set_param("memory_enabled", False)
        self.customer.message_post(
            body=Markup("<p>Historical email from the customer.</p>"),
            author_id=self.contact.id, message_type="comment",
            subtype_xmlid="mail.mt_comment")
        settings.set_param("memory_enabled", True)

    def _count(self):
        return self.env["connect.memory.outbox"].sudo().search_count(
            [("commercial_partner_id", "=", self.customer.id)])

    def test_partner_backfill_enqueues_history_then_idempotent(self):
        self._historical_message()
        self.assertEqual(self._count(), 0)
        self.customer.action_memory_backfill()
        first = self._count()
        self.assertGreater(first, 0, "backfill must queue historical messages")
        self.customer.action_memory_backfill()
        self.assertEqual(self._count(), first,
                         "a second backfill must add nothing (de-dup)")

    def test_memory_event_count_on_partner(self):
        self._historical_message()
        self.customer.action_memory_backfill()
        self.customer.invalidate_recordset(["memory_event_count"])
        self.assertGreater(self.customer.memory_event_count, 0)

    def test_backfill_wizard_creates_and_runs_job(self):
        self._historical_message()
        wizard = self.env["connect.memory.backfill.wizard"].create({
            "date_from": date.today() - timedelta(days=3650),
        })
        wizard.action_preview()
        self.assertGreaterEqual(wizard.estimate, 1)
        action = wizard.action_start()
        job = self.env["connect.memory.backfill"].browse(action["res_id"])
        self.assertTrue(job.exists())
        self.assertGreaterEqual(job.processed, 1)
        self.assertIn(job.state, ("running", "done"))

    def test_backfill_job_lifecycle(self):
        job = self.env["connect.memory.backfill"].create({
            "date_from": date.today() - timedelta(days=30),
        })
        job.action_cancel()
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(job._process_batch(), 0,
                         "a cancelled job must process nothing")
        job.action_resume()
        self.assertEqual(job.state, "running")
