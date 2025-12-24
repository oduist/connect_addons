# -*- coding: utf-8 -*-
"""
ODUIST PROPRIETARY LICENSE
Copyright (c) 2025 Oduist

This file contains license validation logic.
Modification is prohibited under Oduist Proprietary License.
See LICENSE and COPYRIGHT files for full terms.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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

    oduist_module_license_type = fields.Char(
        string="License Type",
        compute="_compute_oduist_license_status",
    )

    def _compute_oduist_license_status(self):
        License = self.env["connect.license"]
        for rec in self:
            status = License.get_license_status(rec.name)

            if status["status"] == "licensed":
                order_id = status.get("order_id", "")
                rec.oduist_license_status = f"Purchase Order: {order_id}" if order_id else "Licensed"
                rec.oduist_module_purchased = True
                rec.oduist_module_license_type = status.get("license_type", "")
            elif status["status"] == "trial_active":
                rec.oduist_license_status = f"Trial: {status['days_left']} days left"
                rec.oduist_module_purchased = False
                rec.oduist_module_license_type = ""
            elif status["status"] == "trial_expired":
                rec.oduist_license_status = "Trial expired"
                rec.oduist_module_purchased = False
                rec.oduist_module_license_type = ""
            elif status["status"] == "demo":
                rec.oduist_license_status = "Demo"
                rec.oduist_module_purchased = True
                rec.oduist_module_license_type = "demo"

    def buy_oduist_license(self):
        """Buy license for this specific module."""
        self.ensure_one()
        License = self.env["connect.license"]
        token = self.env["connect.settings"].sudo().get_param("license_token")
        if not token:
            License.update_license_status()
        return License.buy_licenses([self.name])
