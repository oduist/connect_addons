import json
import logging
import requests
from urllib.parse import urljoin
from odoo import models, fields, api
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)

class AddCredits(models.TransientModel):
    _name = 'connect.add_credits_wizard'
    _description = 'Cancel Subscription'

    pay_amount = fields.Integer(required=True, default=1000)
    receive_amount = fields.Integer(compute='_receive_amount')
    # Receive a copy from the billing system just to calculate excpected amount.
    monthly_average = fields.Integer(readonly=True)
    formula = fields.Char()
    confirm_transaction = fields.Boolean()

    @api.depends('pay_amount')
    def _receive_amount(self):
        for rec in self:
            try:
                k = json.loads(rec.formula)
                months = int(rec.pay_amount / rec.monthly_average)
                if months > 12:
                    # One year deposit maximum.
                    months = 12
                rec.receive_amount = float(k.get(str(months), '1')) * rec.pay_amount
            except Exception as e:
                logger.exception('Error')
                raise ValidationError('Error doing calculation! Please contact billing support!')

    def action_confirm(self):
        if not self.env['connect.settings'].get_param('is_registered'):
            raise ValidationError('Not registered!')
        api_url = self.env['connect.settings'].get_param('api_url')
        url = urljoin(api_url, 'balance')
        res = requests.post(url,
            json={
                'module_name': self.env['connect.settings'].get_param('module_name'),
                'pay_amount': self.pay_amount,
            },
            headers={
                'x-instance-uid': self.env['connect.settings'].get_param('instance_uid') or '',
                'x-api-key': self.env['connect.settings'].get_param('api_key') or ''
            })
        if not res.ok:
            raise ValidationError(res.text)
        data = res.json()
        self.env['connect.settings'].set_param('credits', data['balance'])
