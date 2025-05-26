# -*- coding: utf-8 -*-

import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import debug, format_connect_response

logger = logging.getLogger(__name__)


class ScheduledCall(models.Model):
    _name = 'connect.scheduled_call'
    _description = 'Scheduled Call'

    partner = fields.Many2one('res.partner')
    calling_user = fields.Many2one('res.users')
    calling_pbx_user = fields.Manyone('connect.user')

