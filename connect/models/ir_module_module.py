# -*- coding: utf-8 -*-
import logging

from odoo import fields, models, api

_logger = logging.getLogger(__name__)


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    oduist_license_status = fields.Char(
        string="License Status",
        compute="_compute_oduist_license_status",
    )

    def _compute_oduist_license_status(self):
        License = self.env['connect.license']
        token_data = License.validate_token(
            self.env['connect.settings'].sudo().get_param('license_token')
        )
        for rec in self:
            if token_data and rec.name in token_data.get('modules', {}):
                rec.oduist_license_status = "Licensed"
            else:
                module_status = License.get_license_status(rec.name)
                if module_status.get('status') == 'trial_expired':
                    rec.oduist_license_status = 'Trial expired'
                elif module_status.get('status') == 'trial_active':
                    days_left = module_status.get('days_left', 0)
                    rec.oduist_license_status = f'Trial {days_left} days left'
                else:
                    rec.oduist_license_status = module_status.get('status', 'Unknown')

    def buy_oduist_license(self):
        """Buy license for this specific module."""
        self.ensure_one()
        return self.env['connect.license'].buy_licenses([self.name])
