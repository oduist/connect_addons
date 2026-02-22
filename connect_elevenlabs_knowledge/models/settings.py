# -*- coding: utf-8 -*-

import logging
import urllib.parse
from urllib.parse import urljoin
import requests
import uuid
from elevenlabs import ElevenLabs

from odoo import  models
from odoo.addons.connect.models.settings import PROTECTED_FIELDS


logger = logging.getLogger(__name__)

PROTECTED_FIELDS.append('display_elevenlabs_api_key')
PROTECTED_FIELDS.append('display_elevenlabs_post_call_webhook_secret')

class Elevenlabsettings(models.Model):
    _inherit = 'connect.settings'


