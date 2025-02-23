# -*- coding: utf-8 -*-

from odoo import models, fields


class QueryPrompt(models.Model):
    _name = 'connect.query_prompt'
    _description = 'Connect Query Prompt'

    name = fields.Char(string='Name', required=True)
    content = fields.Text(string='Content', required=True)
