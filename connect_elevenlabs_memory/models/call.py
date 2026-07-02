# -*- coding: utf-8 -*-
from odoo import models


class ConnectCall(models.Model):
    _inherit = "connect.call"

    def _hindsight_personal_bank(self):
        """Bank id for this caller's personal memory:
        partner-<commercial_partner_id> when a partner is known (unifies with
        the `memory` module), else whatsapp-<E164>, else False."""
        self.ensure_one()
        partner = self.partner
        if partner:
            commercial = partner.commercial_partner_id or partner
            return "partner-%s" % commercial.id
        num = (self.caller or "").strip()
        return ("whatsapp-%s" % num) if num else False
