import logging

import phonenumbers
from phonenumbers import parse, format_number, PhoneNumberFormat
from twilio.twiml.messaging_response import MessagingResponse

from odoo import models, fields, api, SUPERUSER_ID
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class ConnectMessage(models.Model):
    _name = 'connect.message'
    _description = 'Twilio Message'
    _order = 'create_date DESC'

    name = fields.Char(string='Name', compute='_compute_name')
    message_sid = fields.Char('Message SID', required=True)
    from_number = fields.Char('From', required=True)
    to_number = fields.Char('To', required=True)
    body = fields.Text('Message Body')
    num_media = fields.Integer('Number of Media Items', default=0)
    message_type = fields.Char(readonly=True)
    status = fields.Char(readonly=True, default='draft')
    # Odoo users
    sender_user = fields.Many2one('res.users', string='Sender User', ondelete='set null', readonly=True)
    sender_user_img = fields.Binary(related='sender_user.image_1920')
    receiver_user = fields.Many2one('res.users', ondelete='set null', string='Receiver User', readonly=True)
    receiver_user_img = fields.Binary(related='receiver_user.image_1920', string='Answered User Avatar')
    partner = fields.Many2one('res.partner', ondelete='set null')
    partner_img = fields.Binary(related='partner.image_1920', string='Partner Image')
    # Geographic information
    from_city = fields.Char('From City')
    from_state = fields.Char('From State')
    from_zip = fields.Char('From ZIP')
    from_country = fields.Char('From Country')
    # Additional Twilio information
    account_sid = fields.Char('Account SID')
    messaging_service_sid = fields.Char('Messaging Service SID')
    has_error = fields.Boolean(index=True)
    error_code = fields.Char()
    error_message = fields.Char()
    res_model = fields.Char()
    res_id = fields.Integer()

    @staticmethod
    def _format_phone_number(number):
        try:
            if number:
                parsed_number = parse(number, None)
                return format_number(parsed_number, PhoneNumberFormat.INTERNATIONAL)
        except phonenumbers.phonenumberutil.NumberParseException:
            return number
        return number

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        for record in res:
            if not record.message_type:
                record.message_type = 'MMS' if record.num_media > 0 else 'SMS'
        return res

    @api.depends('from_number', 'create_date', 'message_type')
    def _compute_name(self):
        for record in self:
            if record.create_date:
                formatted_number = self._format_phone_number(record.from_number)
                record.name = f"{record.message_type} from {formatted_number} on {record.create_date.strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                record.name = f"New {record.message_type}"

    @api.model
    def receive(self, params):
        try:
            if params.get('AccountSid') != self.env['connect.settings'].get_param('account_sid'):
                logger.warning("Received Twilio SMS webhook with incorrect AccountSid")
                return
            if params.get('SmsStatus') == 'received':
                logger.info("Received Twilio SMS webhook data:\n%s", params)
                # Create SMS message record
                from_number = params.get('From')
                to_number = params.get('To')
                values = {
                    'message_sid': params.get('MessageSid'),
                    'from_number': from_number,
                    'to_number': to_number,
                    'body': params.get('Body'),
                    'num_media': int(params.get('NumMedia', 0)),
                    'from_city': params.get('FromCity'),
                    'from_state': params.get('FromState'),
                    'from_zip': params.get('FromZip'),
                    'from_country': params.get('FromCountry'),
                    'account_sid': params.get('AccountSid'),
                    'messaging_service_sid': params.get('MessagingServiceSid'),
                    'status': params.get('SmsStatus'),
                }
                if 'whatsapp:' in from_number:
                    from_number = from_number.replace('whatsapp:', '')
                    to_number = to_number.replace('whatsapp:', '')
                    values.update({
                        'message_type': 'WhatsApp',
                        'from_number': from_number,
                        'to_number': to_number,
                    })
                partner = self.env['res.partner'].get_partner_by_number(from_number)
                if partner:
                    values.update({'partner': partner.id})

                number = self.env['connect.number'].search([('phone_number', '=', to_number)], limit=1)
                if number and number.user:
                    values.update({'receiver_user': number.user.user.id})

                message_id = self.env['connect.message'].sudo().create(values)
                last_message = self.env['connect.message'].search([('from_number', '=', to_number)], limit=1)
                if last_message and last_message.res_model and last_message.res_id:
                    mt_note = self.env.ref('mail.mt_note').id
                    obj = self.env[last_message.res_model].browse(last_message.res_id)
                    if hasattr(obj, 'message_post'):
                        kwargs = {
                            'body': params.get('Body'),
                            'subtype_id': mt_note,
                        }
                        if partner:
                            kwargs.update({'author_id': partner.id})
                        else:
                            kwargs.update({'body': 'From: {}. Message: {}'.format(from_number, params.get('Body'))})
                        obj.with_user(SUPERUSER_ID).with_context(mail_create_nosubscribe=False).message_post(**kwargs)
            else:
                # Update message status
                logger.info("Received Update Twilio SMS webhook data:\n%s", params)
                message = self.env['connect.message'].sudo().search([('message_sid', '=', params.get('MessageSid'))])
                message.update({'status': params.get('SmsStatus')})
                if params.get('SmsStatus') == 'failed':
                    message.update({
                        'error_code': params.get('ErrorCode'),
                        'error_message': params.get('ErrorMessage'),
                        'has_error': True
                    })
        except Exception as e:
            logger.error(f"Error handling incoming SMS: {e}")
        finally:
            return str(MessagingResponse())  # Return empty TwiML response, i.e. no reply.

    def send(self, recipient, body, res_id=None, res_model=None):
        sender_user_id = self.env.user.id
        number = self.env['connect.number'].search([('user.user', '=', sender_user_id)], limit=1)
        # Check if user have a number
        if not number:
            raise ValidationError('You dont have a number!')
        sender = number.phone_number
        message = self.client_send(recipient, sender, body, whatsapp=True)
        if not message:
            message = self.client_send(recipient, sender, body)
        if not message:
            raise ValidationError('Unexpected error! Contact admin or maintainer!')
        # Create message record
        partner = self.env['res.partner'].get_partner_by_number(recipient)
        self.env['connect.message'].sudo().create({
            'account_sid': message.account_sid,
            'from_number': sender,
            'to_number': recipient,
            'body': body,
            'partner': partner.id,
            'sender_user': sender_user_id,
            'messaging_service_sid': message.messaging_service_sid,
            'num_media': message.num_media,
            'error_code': message.error_code,
            'error_message': message.error_message,
            'message_sid': message.sid,
            'res_id': res_id,
            'res_model': res_model,
            'status': 'sent'
        })

    def client_send(self, recipient, sender, body, whatsapp=False):
        try:
            client = self.env['connect.settings'].get_client()
            # Send message to twilio
            message = client.messages.create(
                to='whatsapp:{}'.format(recipient) if whatsapp else recipient,
                from_='whatsapp:{}'.format(sender) if whatsapp else sender,
                body=body,
            )
            if message.error_code == '63003':
                return False
            return message
        except Exception as e:
            if not whatsapp:
                logger.exception(e)
            else:
                logger.info('Unable to send WhatsUp message to "{}"!'.format(recipient))
            return False
