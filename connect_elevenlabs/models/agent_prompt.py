# -*- coding: utf-8 -*-
from odoo import models, fields


class ElevenlabsAgentPrompt(models.Model):
    _name = 'connect.elevenlabs_agent_prompt'
    _description = 'Elevenlabs Agent Prompt Version'

    name = fields.Char(required=True)
    agent = fields.Many2one('connect.elevenlabs_agent', required=True, ondelete='cascade')
    prompt = fields.Text(required=True)
