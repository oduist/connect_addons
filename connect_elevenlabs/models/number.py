# -*- coding: utf-8 -*-

import logging
from urllib.parse import urlparse

from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml

logger = logging.getLogger(__name__)


class ElevenlabsNumber(models.Model):
    _inherit = 'connect.number'

    destination = fields.Selection(selection_add=[('elevenlabs_agent', 'Agent')])
    elevenlabs_agent = fields.Many2one('connect.elevenlabs_agent', ondelete='set null')

    def write(self, vals):
        if 'destination' in vals:
            if 'elevenlabs_agent' != vals['destination']:
                vals.update({'elevenlabs_agent': None})
        return super().write(vals)

    @api.model
    def route_call(self, request):
        res = super().route_call(request)
        number = self.search([('phone_number', '=', request['Called'])])
        if number.destination == 'elevenlabs_agent' and number.elevenlabs_agent:
            return number.elevenlabs_agent.render(request)
        return res
