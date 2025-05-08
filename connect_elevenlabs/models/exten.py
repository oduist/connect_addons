# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, release, api

logger = logging.getLogger(__name__)


class Exten(models.Model):
    _inherit = 'connect.exten'

    dst = fields.Reference(selection_add=[('connect.elevenlabs_agent', 'Agent')])
