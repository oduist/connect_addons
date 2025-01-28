from odoo import api, fields, models


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    def send(self, **kwargs):
        pass