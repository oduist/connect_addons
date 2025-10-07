# -*- coding: utf-8 -*-

from odoo import fields, models, api


class OutgoingCallerIDByoc(models.Model):
    _inherit = 'connect.outgoing_callerid'

    # Add byoc field as Many2one to reference BYOC configuration
    byoc = fields.Many2one(
        'connect.byoc',
        string='BYOC',
        help='Bring Your Own Carrier configuration for this number',
        ondelete='cascade'
    )

    # Extend the callerid_type selection to include 'byoc'
    callerid_type = fields.Selection(
        selection_add=[('byoc', 'BYOC')],
        ondelete={'byoc': 'cascade'}
    )

    @api.onchange('byoc')
    def _onchange_byoc(self):
        """When byoc field is changed, update the callerid_type accordingly"""
        if self.byoc:
            self.callerid_type = 'byoc'
        else:
            # If clearing byoc, set to outgoing_callerid as default for manual entries
            if self.callerid_type == 'byoc':
                self.callerid_type = 'outgoing_callerid'

    @api.onchange('callerid_type')
    def _onchange_callerid_type(self):
        """When callerid_type is changed, clear byoc if not byoc type"""
        if self.callerid_type != 'byoc':
            self.byoc = False