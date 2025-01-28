from odoo import api, models, fields
from odoo.exceptions import ValidationError


class AddToCallout(models.TransientModel):
    _name = 'connect.manage_partner_callout_wizard'
    _description = 'Manage Partner Callout'

    available_callouts = fields.Many2many(comodel_name='connect.callout')
    callout = fields.Many2one('connect.callout')
    action = fields.Selection([('add', 'Add'), ('remove', 'Remove')])

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('default_action') == 'remove':
            res['available_callouts'] = self.env['connect.callout'].search([
                ('contacts.partner', 'in', self.env.context["active_ids"]),
            ])
        else:
            res['available_callouts'] = self.env['connect.callout'].search([])
        return res

    def _compute_available_callout(self):
        for wizard in self:
            wizard.available_callouts = self.env['connect.callout'].search([
                ('contacts.partner', 'in', self.env.context["active_ids"]),
            ])
            print('---_compute_available_callout', wizard.available_callouts)

    def submit(self):
        if self.callout:
            if self.action == 'add':
                self.add_to_callout(self.callout)
            elif self.action == 'remove':
                self.remove_from_callout(self.callout)
        else:
            raise ValidationError('Please check the confirm box!')

    def add_to_callout(self, callout):
        context = self.env.context
        partners = self.env['res.partner'].browse(context["active_ids"])
        payload = []
        for partner in partners:
            if partner.phone:
                payload.append({
                    'callout': callout.id,
                    'phone_number': partner.phone,
                    'partner': partner.id
                })
            if partner.mobile:
                payload.append({
                    'callout': callout.id,
                    'phone_number': partner.mobile,
                    'partner': partner.id
                })
        if payload:
            self.env['connect.callout_contact'].create(payload)

    def remove_from_callout(self, callout):
        callout_contacts = self.env['connect.callout_contact'].search([
            ('partner', 'in', self.env.context["active_ids"]),
            ('callout', '=', callout.id)
        ])
        callout_contacts.unlink()
