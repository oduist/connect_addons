# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
from datetime import datetime, timedelta
from odoo import models, fields, api


class Debug(models.Model):
    _name = 'connect.debug'
    _description = 'Asterisk Debug'
    _order = 'id desc'
    _rec_name = 'id'

    model = fields.Char()
    message = fields.Text()


    @api.model
    def vacuum(self, hours=24):
        """Cron job to delete debug data records.
        """
        expire_date = datetime.utcnow() - timedelta(hours=hours)
        records = self.env['connect.debug'].search([
            ('create_date', '<=', expire_date.strftime('%Y-%m-%d %H:%M:%S'))
        ])
        records.unlink()
