# -*- coding: utf-8 -*-

import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from odoo.addons.connect.models.settings import format_connect_response, debug
from odoo.addons.connect.models.twiml import pretty_xml


logger = logging.getLogger(__name__)


class ByocNumber(models.Model):
    _inherit = "connect.number"

    byoc = fields.Many2one('connect.byoc', string='BYOC', ondelete='cascade')

    def write(self, vals):
        # We don't support updating multiple records.
        self.ensure_one()
        if self.byoc:
            return super(ByocNumber, self.with_context(skip_twilio_sync=True)).write(vals)
        else:
            return super(ByocNumber, self).write(vals)
