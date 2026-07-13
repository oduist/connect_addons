from markupsafe import Markup

from odoo.tests import tagged

from .common import MemoryCommon


@tagged("post_install", "-at_install")
class TestCapture(MemoryCommon):
    """Live capture of customer correspondence on the chatter of any document
    (here res.partner), via the mail.thread.message_post override."""

    def test_inbound_message_creates_event(self):
        self._post_inbound(subject="Order status")
        events = self._events_for(self.customer)
        self.assertTrue(events, "an inbound customer message must be captured")
        ev = events[-1]
        self.assertEqual(ev["domain"], "partner")
        self.assertEqual(ev["kind"], "message")
        self.assertEqual(ev["actor"]["direction"], "in")
        self.assertEqual(ev["sensitivity"], "personal")
        self.assertEqual(ev["scope"]["commercial_partner_id"], self.customer.id)
        self.assertEqual(ev["scope"]["partner_id"], self.contact.id)
        self.assertIn("dir:in", ev["tags"])
        self.assertIn("from:%s" % self.contact.id, ev["tags"])

    def test_inbound_text_is_html_stripped(self):
        self._post_inbound(body="<p>Hello <b>bold</b> world</p>")
        ev = self._events_for(self.customer)[-1]
        self.assertNotIn("<", ev["text"], "HTML must be flattened to plain text")
        self.assertIn("bold", ev["text"])

    def test_outbound_message_direction_and_user_scope(self):
        self._post_outbound()
        ev = self._events_for(self.customer)[-1]
        self.assertEqual(ev["actor"]["direction"], "out")
        self.assertIn("to:%s" % self.contact.id, ev["tags"])
        self.assertIn("user_id", ev["scope"],
                      "an internal author must be recorded in the scope")

    def test_dedup_key_is_stable_per_message_and_company(self):
        message = self._post_inbound()
        row = self._rows_for(self.customer)[-1]
        self.assertEqual(
            row.dedup_key,
            "mail.message-%s-c%s" % (message.id, self.customer.id))

    def test_internal_note_is_not_captured(self):
        before = len(self._rows_for(self.customer))
        self.customer.message_post(
            body=Markup("<p>internal note, do not capture</p>"),
            author_id=self.contact.id, message_type="comment",
            subtype_xmlid="mail.mt_note")
        self.assertEqual(len(self._rows_for(self.customer)), before,
                         "log notes (mt_note) must never be captured")

    def test_internal_author_without_external_recipient_is_skipped(self):
        before = len(self._rows_for(self.customer))
        self.customer.with_user(self.agent).message_post(
            body=Markup("<p>just an internal ops log</p>"),
            message_type="comment", subtype_xmlid="mail.mt_comment")
        self.assertEqual(len(self._rows_for(self.customer)), before,
                         "internal message with no external party is not memory")

    def test_master_switch_off_captures_nothing(self):
        self.env["connect.settings"].sudo().set_param("memory_enabled", False)
        before = len(self._rows_for(self.customer))
        self._post_inbound()
        self.assertEqual(len(self._rows_for(self.customer)), before,
                         "no capture while the master switch is off")

    def test_is_external_classification(self):
        thread = self.env["mail.thread"]
        self.assertTrue(thread._memory_is_external(self.contact))
        self.assertFalse(
            thread._memory_is_external(self.agent.partner_id),
            "an internal user's partner is not external")
        self.assertFalse(
            thread._memory_is_external(self.env.company.partner_id),
            "our own company is not external")
        self.assertFalse(thread._memory_is_external(self.env["res.partner"]))

    def test_should_capture_gate(self):
        message = self._post_inbound()
        self.assertTrue(self.customer._memory_should_capture(message))
        self.env["connect.settings"].sudo().set_param("memory_enabled", False)
        self.assertFalse(
            self.customer._memory_should_capture(message),
            "switch off -> the gate must refuse capture")
