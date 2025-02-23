# -*- coding: utf-8 -*-

from odoo import api, models, fields


class QuerySource(models.Model):
    _name = 'connect.query_source'
    _description = 'Query Source'

    name = fields.Char(string="Name", required=True)
    model_id = fields.Many2one('ir.model', string="Model", required=True, ondelete='cascade')
    model_name = fields.Char(string="Model Name", related="model_id.model")
    field_ids = fields.Many2many(
        'ir.model.fields', string="Fields",
        domain="[('model_id', '=', model_id)]"
    )
    domain = fields.Char(string="Domain")

    @api.onchange('model_id')
    def _onchange_model_id(self):
        """Ensure that the domain is cleared when the model is changed."""
        self.field_ids = False
