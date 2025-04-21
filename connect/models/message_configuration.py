from odoo import api, models, fields
import ast

from odoo.exceptions import ValidationError


class ConnectMessageConfiguration(models.Model):
    _name = 'connect.message_configuration'
    _description = 'Twilio Message Configuration'
    _rec_name = 'id'

    number = fields.Many2one('connect.number', required=True)
    model = fields.Many2one('ir.model', required=True, ondelete='cascade')
    default_values = fields.Text(default='{}')

    @api.constrains('default_values')
    def _check_default_values(self):
        for alias in self:
            try:
                dict(ast.literal_eval(alias.default_values))
            except Exception as e:
                raise ValidationError(
                    'Invalid expression, it must be a literal python dictionary definition e.g. "{\'field\': \'value\'}"'
                ) from e
