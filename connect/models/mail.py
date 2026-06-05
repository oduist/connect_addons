from odoo import api, fields, models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    connect_message = fields.Many2one('connect.message')
    message_type = fields.Selection(
        selection_add=[
            ('WhatsApp', 'WhatsApp'),
            ('connect_message', 'Connect Message'),
        ],
        ondelete={
            'WhatsApp': lambda recs: recs.write({'message_type': 'comment'}),
            'connect_message': lambda recs: recs.write({'message_type': 'comment'}),
        },
    )

    @api.model
    def get_message_numbers(self, message_id):
        mail = self.browse(message_id)
        message = mail.connect_message
        if message:
            number = self.env['connect.number'].search([('phone_number', '=', message.to_number)])
            return {'from_number': message.from_number, 'to_number': message.to_number}
        else:
            return False

    def _to_store(self, store, **kwargs):
        super()._to_store(store, **kwargs)
        linked = self.filtered(
            lambda m: m.message_type == 'connect_message' and m.connect_message)
        for message in linked:
            store.add(message, {
                'connectStatus': message.connect_message.status,
                'connectMessageType': message.connect_message.message_type,
            })


class MailNotification(models.Model):
    _inherit = 'mail.notification'

    notification_type = fields.Selection(selection_add=[
        ('WhatsApp', 'WhatsApp')
    ], ondelete={'WhatsApp': 'cascade'})


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _connect_calls(self):
        call_ids = {a.res_id for a in self if a.res_model == 'connect.call' and a.res_id}
        return self.env['connect.call'].browse(call_ids)

    @api.model_create_multi
    def create(self, vals_list):
        activities = super().create(vals_list)
        activities._connect_calls()._recompute_has_activity()
        return activities

    def write(self, vals):
        calls = self._connect_calls()
        res = super().write(vals)
        (calls | self._connect_calls())._recompute_has_activity()
        return res

    def unlink(self):
        calls = self._connect_calls()
        res = super().unlink()
        calls._recompute_has_activity()
        return res
