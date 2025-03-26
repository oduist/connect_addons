# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, release, api

logger = logging.getLogger(__name__)


class AIagent(models.Model):
    _name = 'connect_elevenlabs.ai_agent'
    _rec_name = 'agent_name'

    agent_name = fields.Char(required=True)
    agent_id = fields.Char(string="Agent ID", required=True)
