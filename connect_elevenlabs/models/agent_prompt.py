# -*- coding: utf-8 -*-
from odoo import models, fields


class ElevenlabsAgentPrompt(models.Model):
    _name = 'connect.elevenlabs_agent_prompt'
    _description = 'Elevenlabs Agent Prompt Version'
    _order = 'id desc'

    name = fields.Char(required=True)
    agent = fields.Many2one('connect.elevenlabs_agent', required=True, ondelete='cascade')
    prompt = fields.Text(required=True)
