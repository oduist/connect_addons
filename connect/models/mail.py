from odoo import api, fields, models, release


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

    if release.version_info[0] >= 17:
        def _to_store(self, store, *args, **kwargs):
            super()._to_store(store, *args, **kwargs)
            linked = self.filtered(
                lambda m: m.message_type == 'connect_message' and m.connect_message)
            for message in linked:
                cmsg = message.sudo().connect_message
                # add_records_fields (not add) avoids re-entering _to_store recursively.
                store.add_records_fields(message, {
                    'connectStatus': cmsg.status,
                    'connectMessageType': cmsg.message_type,
                })
    else:
        def message_format(self, format_reply=True):
            values = super().message_format(format_reply=format_reply)
            by_id = {message.id: message.sudo() for message in self}
            for value in values:
                message = by_id.get(value['id'])
                if (message and message.message_type == 'connect_message'
                        and message.connect_message):
                    value.update({
                        'connectStatus': message.connect_message.status,
                        'connectMessageType': message.connect_message.message_type,
                    })
            return values


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
