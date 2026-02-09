# -*- coding: utf-8 -*-
from odoo import models, fields


class ElevenlabsAgentTransferExten(models.Model):
    _name = 'connect.elevenlabs_agent_transfer_exten'
    _description = 'Elevenlabs Agent Transfer to Extension'

    agent = fields.Many2one('connect.elevenlabs_agent', required=True, ondelete='cascade')
    transfer_to_exten = fields.Many2one('connect.exten', required=True, ondelete='cascade')
    condition = fields.Char(string="Condition")
