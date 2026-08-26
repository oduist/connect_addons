import json

from markupsafe import Markup

from odoo.tests import TransactionCase


class MemoryCommon(TransactionCase):
    """Shared fixtures for connect_memory tests.

    Builds one external customer company with a contact (neither is linked to
    an internal user nor to one of our own companies, so both are memory
    targets) and grabs a real internal user to act as "our agent". The master
    capture switch and a service token are turned on for the whole class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings = cls.env["connect.settings"].sudo()
        settings.set_param("memory_enabled", True)
        settings.set_param("memory_service_token", "test-token-123")
        cls.customer = cls.env["res.partner"].create({
            "name": "Umbrella Corp",
            "is_company": True,
            "email": "info@umbrella.example",
        })
        cls.contact = cls.env["res.partner"].create({
            "name": "Alice",
            "parent_id": cls.customer.id,
            "email": "alice@umbrella.example",
        })
        # a real non-share user is required so its partner is NOT external
        cls.agent = cls.env.ref("base.user_admin")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _rows_for(self, commercial):
        return self.env["connect.memory.outbox"].sudo().search(
            [("commercial_partner_id", "=", commercial.id)], order="id")

    def _events_for(self, commercial):
        return [json.loads(r.payload) for r in self._rows_for(commercial) if r.payload]

    def _post_inbound(self, doc=None, body="<p>When will my order ship?</p>",
                      subject=None):
        """A message authored by the external contact -> direction 'in'."""
        doc = doc or self.customer
        return doc.message_post(
            body=Markup(body), subject=subject, author_id=self.contact.id,
            message_type="comment", subtype_xmlid="mail.mt_comment")

    def _post_outbound(self, doc=None, body="<p>It ships tomorrow.</p>"):
        """A message from our internal agent to the external contact -> 'out'."""
        doc = doc or self.customer
        return doc.with_user(self.agent).message_post(
            body=Markup(body), partner_ids=[self.contact.id],
            message_type="comment", subtype_xmlid="mail.mt_comment")
