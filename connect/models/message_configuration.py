from odoo import models, fields, api
import ast
from odoo.exceptions import ValidationError


class ConnectMessageConfiguration(models.Model):
    _name = 'connect.message_configuration'
    _description = 'Message Handling Configuration'
    _rec_name = 'id'

    number = fields.Many2one('connect.number', required=True)
    destination = fields.Selection([
        ('res.partner', 'Partner'),
    ], required=True, default='res.partner', help='Destination model to create records from messages.')
    default_values = fields.Text(default='{}')

    @api.constrains('default_values')
    def _check_default_values(self):
        for rec in self:
            try:
                dict(ast.literal_eval(rec.default_values or '{}'))
            except Exception as e:
                raise ValidationError(
                    "Invalid expression, it must be a literal python dictionary definition e.g. '{\'field\': \'value\'}'"
                ) from e
