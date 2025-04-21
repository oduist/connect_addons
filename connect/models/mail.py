from odoo import api, fields, models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    connect_message = fields.Many2one('connect.message')
    message_type = fields.Selection(
        selection_add=[('WhatsApp', 'WhatsApp')],
        ondelete={'WhatsApp': lambda recs: recs.write({'message_type': 'comment'})},
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


class MailNotification(models.Model):
    _inherit = 'mail.notification'

    notification_type = fields.Selection(selection_add=[
        ('WhatsApp', 'WhatsApp')
    ], ondelete={'WhatsApp': 'cascade'})
