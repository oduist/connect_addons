# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OriginateToWizard(models.TransientModel):
    _name = 'connect.originate_to_wizard'
    _description = 'Connect Partner To'

    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)
    number = fields.Char(string='Call To', required=True, help='Phone number to call (partner number)')
    extension_id = fields.Many2one(
        'connect.exten',
        string='Extension',
        required=True,
        help='Extension to connect to after partner answers'
    )
    outgoing_callerid_id = fields.Many2one(
        'connect.outgoing_callerid',
        string='Caller ID',
        required=True,
        domain="['|', ('status', '=', 'validated'), ('callerid_type', '=', 'number')]",
        help='Caller ID to display'
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = dict(self.env.context or {})

        # Get partner from context
        partner_id = ctx.get('active_id')
        if ctx.get('active_model') == 'res.partner' and partner_id:
            partner = self.env['res.partner'].browse(partner_id)
            vals['partner_id'] = partner_id

            # Default number from partner
            phone = partner.phone or partner.mobile
            if phone:
                try:
                    phone = self.env['res.partner']._phone_format(number=phone)
                except Exception:
                    pass
                vals['number'] = phone

        # Default outgoing callerid
        user = self.env.user
        if user.connect_user and user.connect_user.outgoing_callerid:
            vals['outgoing_callerid_id'] = user.connect_user.outgoing_callerid.id
        else:
            default_callerid = self.env['connect.outgoing_callerid'].search(
                [('is_default', '=', True)], limit=1
            )
            if default_callerid:
                vals['outgoing_callerid_id'] = default_callerid.id

        return vals

    def action_originate(self):
        """Originate a call connecting partner to an extension."""
        self.ensure_one()
        if not self.number:
            raise ValidationError('Phone number to call is required')
        if not self.extension_id:
            raise ValidationError('Extension is required')
        if not self.outgoing_callerid_id:
            raise ValidationError('Caller ID is required')

        self.env['res.partner'].originate_call_to(
            number=self.number,
            extension_id=self.extension_id.id,
            callerid=self.outgoing_callerid_id.number,
            partner_id=self.partner_id.id if self.partner_id else False,
        )
        return {'type': 'ir.actions.act_window_close'}
