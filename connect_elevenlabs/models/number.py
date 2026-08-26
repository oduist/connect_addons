# -*- coding: utf-8 -*-
"""Route inbound DIDs whose destination is an ElevenLabs agent.

The base ``connect.number`` model dispatches inbound calls by ``destination``
(User / CallFlow / TwiML / SIP Trunk). This extension re-adds the
``elevenlabs_agent`` destination so a phone number can route straight to an
agent, rendered as TwiML that dials ElevenLabs' SIP ingress
(see ``connect.elevenlabs_agent.render``).

This is also the destination the ``1.0.7`` migration repoints numbers to,
so the model must exist for those numbers to resolve.
"""
import logging

from odoo import fields, models

logger = logging.getLogger(__name__)


class ElevenlabsNumber(models.Model):
    _inherit = 'connect.number'

    destination = fields.Selection(
        selection_add=[('elevenlabs_agent', 'Agent')],
        ondelete={'elevenlabs_agent': 'set null'})
    elevenlabs_agent = fields.Many2one(
        'connect.elevenlabs_agent', ondelete='set null',
        help='ElevenLabs agent inbound calls to this number are routed to.')

    def write(self, vals):
        # Clear the agent link when the number is repointed elsewhere,
        # mirroring how the base model clears user/callflow/twiml.
        if vals.get('destination') and vals['destination'] != 'elevenlabs_agent':
            vals = dict(vals, elevenlabs_agent=False)
        return super().write(vals)

    def render(self, request={}, params={}):
        self.ensure_one()
        if self.destination == 'elevenlabs_agent' and self.elevenlabs_agent:
            return self.elevenlabs_agent.render(request)
        return super().render(request=request, params=params)
