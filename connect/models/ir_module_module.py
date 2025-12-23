# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TRIAL_DAYS = 30


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    oduist_license_status = fields.Char(
        string="License Status",
        compute="_compute_oduist_license_status",
    )

    oduist_module_purchased = fields.Boolean(
        string="Module Purchased",
        compute="_compute_oduist_license_status",
    )

    oduist_module_description = fields.Char()

    def _compute_oduist_license_status(self):
        License = self.env["connect.license"]
        token = self.env["connect.settings"].sudo().get_param("license_token")
        token_data = License.validate_token(token) if token else None
        purchased_modules = token_data.get("purchased_modules", {}) if token_data else {}

        for rec in self:
            if rec.name in purchased_modules:
                order_id = purchased_modules[rec.name].get("order_id", "")
                rec.oduist_license_status = f"Purchase Order: {order_id}" if order_id else "Licensed"
                rec.oduist_module_purchased = True
            else:
                install_date = rec.create_date or datetime.now() - timedelta(days=TRIAL_DAYS)
                days_passed = (datetime.now() - install_date).days
                days_left = max(0, TRIAL_DAYS - days_passed)

                if days_left > 0:
                    rec.oduist_license_status = f"Trial: {days_left} days left"
                else:
                    rec.oduist_license_status = "Trial expired"
                rec.oduist_module_purchased = False

    def buy_oduist_license(self):
        """Buy license for this specific module."""
        self.ensure_one()
        License = self.env["connect.license"]
        token = self.env["connect.settings"].sudo().get_param("license_token")
        if not token:
            License.update_license_status()
        return License.buy_licenses([self.name])
