# -*- coding: utf-8 -*-

import logging
from urllib.parse import urlparse

from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml

logger = logging.getLogger(__name__)


class Number(models.Model):
    _inherit = 'connect.number'

