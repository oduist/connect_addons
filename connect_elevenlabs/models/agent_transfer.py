# -*- coding: utf-8 -*-
from odoo import models, fields


class ElevenlabsAgentTransfer(models.Model):
    _name = 'connect.elevenlabs_agent_transfer'
    _description = 'Elevenlabs Agent Transfer'

    agent = fields.Many2one('connect.elevenlabs_agent', required=True, ondelete='cascade')
    transfer_to_agent = fields.Many2one('connect.elevenlabs_agent', required=True, ondelete='cascade',
                                        domain="[('id', '!=', agent)]")
    condition = fields.Char(string="Condition")
