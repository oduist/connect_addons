# -*- coding: utf-8 -*-
import logging

from odoo import api, models

from . import hindsight_client

logger = logging.getLogger(__name__)


class ConnectRecording(models.Model):
    _inherit = "connect.recording"

    def _memory_module_present(self):
        return "memory.outbox" in self.env

    def _hindsight_retain_text(self):
        self.ensure_one()
        summary = self.elevenlabs_summary or ""
        transcript = self.elevenlabs_transcript or ""
        return ("%s\n\n%s" % (summary, transcript)).strip()

    def _retain_to_hindsight(self):
        """Push this recording's transcript into the caller's partner bank.
        Never raises into call handling."""
        for rec in self:
            try:
                cfg = self.env["connect.settings"].sudo().get_hindsight_config()
                if not cfg["enabled"] or not cfg["api_key"]:
                    continue
                partner = rec.partner
                if not partner:
                    continue
                text = rec._hindsight_retain_text()
                if not text:
                    continue
                commercial = partner.commercial_partner_id or partner
                bank = "partner-%s" % commercial.id
                dedup = "connect-recording-%s" % rec.id
                if rec._memory_module_present():
                    outbox = self.env["memory.outbox"].sudo()
                    envelope = {
                        "domain": "voice",
                        "kind": "call",
                        "dedup_key": dedup,
                        "text": text,
                        "content_hash": outbox._memory_content_hash(text),
                        "scope": {
                            "commercial_partner_id": commercial.id,
                            "commercial_partner_name": commercial.display_name,
                        },
                        "source": {
                            "model": "connect.recording",
                            "res_id": rec.id,
                            "company_id": self.env.company.id,
                        },
                    }
                    outbox.enqueue(envelope)
                else:
                    hindsight_client.retain(
                        cfg["base"], cfg["tenant"], cfg["api_key"], bank, text,
                        document_id=dedup, context="voice/call")
            except Exception as e:
                logger.warning("Hindsight retain failed for recording %s: %s", rec.id, e)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._retain_to_hindsight()
        return records
