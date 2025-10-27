# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ConnectWhatsappComposer(models.TransientModel):
    _name = 'connect.whatsapp_composer'
    _description = 'Send WhatsApp Message'

    # Context/target
    res_model = fields.Char('Related Model')
    res_id = fields.Integer('Related Record')

    # Inputs
    whatsapp_sender_id = fields.Many2one('connect.whatsapp_sender', string='Sender', required=True)
    phone = fields.Char(string='To', required=True)
    body = fields.Text(string='Message', required=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = dict(self.env.context or {})
        res_model = ctx.get('active_model') or ctx.get('default_res_model')
        res_id = ctx.get('active_id') or ctx.get('default_res_id')
        vals.update({'res_model': res_model, 'res_id': res_id})

        # Default sender: user preference -> default sender -> any sender
        sender = False
        connect_user = self.env.user.connect_user
        if connect_user and connect_user.whatsapp_sender_id:
            sender = connect_user.whatsapp_sender_id
        if not sender:
            sender = self.env['connect.whatsapp_sender'].search([('is_default', '=', True)], limit=1)
        if not sender:
            sender = self.env['connect.whatsapp_sender'].search([], limit=1)
        if sender:
            vals['whatsapp_sender_id'] = sender.id

        # Default phone
        phone = ctx.get('default_phone')
        try:
            if not phone and res_model and res_id and res_model in self.env:
                rec = self.env[res_model].browse(res_id)
                # Prefer normalized fields then mobile then phone
                phone = rec.connect_mobile_normalized or rec.connect_phone_normalized or rec.mobile or rec.phone
            if phone:
                # Normalize to E.164 using partner helper
                phone = self.env['res.partner']._phone_format(number=phone)
        except Exception:
            pass
        if phone:
            vals['phone'] = phone

        return vals

    def action_send_whatsapp(self):
        self.ensure_one()
        if not self.phone:
            raise ValidationError('Recipient number is required')
        self.whatsapp_sender_id.send_whatsapp(
            recipient=self.phone,
            body=self.body,
            res_model=self.res_model,
            res_id=self.res_id,
        )
        return {'type': 'ir.actions.act_window_close'}
