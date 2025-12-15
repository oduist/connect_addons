# -*- coding: utf-8 -*-
from odoo import fields, models


class ConnectModule(models.Model):
    """
    Service model to track installed Connect modules and their installation dates.
    Used for trial period calculation (30 days from create_date).
    """
    _name = 'connect.module'
    _description = 'Connect Module Installation Tracker'

    name = fields.Char(string='Module Name', required=True, index=True)
    description = fields.Char(string='Description')

    _sql_constraints = [
        ('name_unique', 'UNIQUE(name)', 'Module name must be unique!')
    ]
