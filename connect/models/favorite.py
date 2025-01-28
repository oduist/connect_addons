# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
from odoo import models, fields


class Favorite(models.Model):
    _name = 'connect.favorite'
    _order = 'id desc'
    _description = 'Favorite'

    name = fields.Char()
    phone_number = fields.Char(required=True)
    user = fields.Many2one('res.users', ondelete='set null')
    partner = fields.Many2one('res.partner', ondelete='set null')
