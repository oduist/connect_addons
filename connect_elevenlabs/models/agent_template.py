# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

logger = logging.getLogger(__name__)


class ElevenlabsAgentTemplate(models.Model):
    _name = 'connect.elevenlabs_agent_template'
    _description = 'Elevenlabs Agent Template'

    name = fields.Char(required=True, index=True)
    system_prompt = fields.Html(required=True, help='System prompt template for the agent')
