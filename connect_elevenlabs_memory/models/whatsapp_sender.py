# -*- coding: utf-8 -*-
from odoo import models


class ConnectWhatsappSender(models.Model):
    _inherit = "connect.whatsapp_sender"

    def action_route_calls_to_agent(self, agent):
        """Route inbound WhatsApp calls on this sender's number to an ElevenLabs
        agent by creating/updating a matching connect.exten. `route_call` looks
        up the extension by the dialed WhatsApp number, so number must equal the
        sender number in E.164."""
        self.ensure_one()
        Exten = self.env["connect.exten"]
        exten = Exten.search([("number", "=", self.number)], limit=1)
        vals = {"number": self.number, "model": "connect.elevenlabs_agent",
                "res_id": agent.id}
        if exten:
            exten.write(vals)
        else:
            exten = Exten.create(vals)
        return exten
