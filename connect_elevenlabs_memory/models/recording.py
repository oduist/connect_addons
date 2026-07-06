# -*- coding: utf-8 -*-
import logging

from odoo import api, models

logger = logging.getLogger(__name__)


class ConnectRecording(models.Model):
    _inherit = "connect.recording"

    def _memory_retain_text(self):
        self.ensure_one()
        summary = self.elevenlabs_summary or ""
        transcript = self.elevenlabs_transcript or ""
        return ("%s\n\n%s" % (summary, transcript)).strip()

    def _retain_to_memory(self):
        """Enqueue this recording's transcript into the caller's partner bank via
        memory.outbox; the gateway performs the Hindsight retain (one write path,
        unified with the rest of Oduist Memory). Never raises into call handling."""
        icp = self.env["ir.config_parameter"].sudo()
        if icp.get_param("memory.enabled") not in ("1", "True", "true"):
            return
        outbox = self.env["memory.outbox"].sudo()
        for rec in self:
            try:
                partner = rec.partner
                if not partner:
                    continue
                text = rec._memory_retain_text()
                if not text:
                    continue
                commercial = partner.commercial_partner_id or partner
                outbox.enqueue({
                    "domain": "voice",
                    "kind": "call",
                    "dedup_key": "connect-recording-%s" % rec.id,
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
                })
            except Exception as e:
                logger.warning("Memory retain failed for recording %s: %s", rec.id, e)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._retain_to_memory()
        return records
