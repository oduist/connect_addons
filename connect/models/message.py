# -*- coding: utf-8 -*-
"""
ODUIST PROPRIETARY LICENSE
Copyright (c) 2025 Oduist

This file contains license validation logic.
Modification is prohibited under Oduist Proprietary License.
See LICENSE and COPYRIGHT files for full terms.
"""

import ast
import logging
import os
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin

import openai
import phonenumbers
import requests
from markupsafe import Markup
from phonenumbers import parse, format_number, PhoneNumberFormat
from twilio.twiml.messaging_response import MessagingResponse

from odoo import models, fields, api, SUPERUSER_ID, release
from odoo.exceptions import ValidationError
from odoo.tools import mail

logger = logging.getLogger(__name__)

mail.safe_attrs = mail.safe_attrs | frozenset(['controls'])


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
    direction = fields.Selection([
        ('incoming', 'Incoming'),
        ('outgoing', 'Outgoing'),
    ], compute='_compute_direction', store=True, readonly=True)
    direction_display = fields.Html(compute='_compute_direction_display', sanitize=False)
    status = fields.Char(readonly=True, default='draft')
    status_display = fields.Html(compute='_compute_status_display', sanitize=False)
    # Odoo users
    sender_user = fields.Many2one('res.users', string='Sender User', ondelete='set null', readonly=True)
    sender_user_img = fields.Binary(related='sender_user.image_1920')
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
    ref = fields.Reference(selection='_reference_models', string="Reference", compute='_compute_ref', store=True)
    parent_message = fields.Many2one('connect.message', string='In Reply To', readonly=True)
    media_url = fields.Char()
    media_content_type = fields.Char()
    transcription_error = fields.Char()
    if release.version_info[0] >= 17.0:
        media_widget = fields.Html(compute='_get_media_widget', string='Media', sanitize=False)
    else:
        media_widget = fields.Char(compute='_get_media_widget', string='Media')

    def _get_media_widget(self):
        for rec in self:
            html = ''
            url = rec.media_url or ''
            ctype = (rec.media_content_type or '').lower()
            if url:
                if ctype.startswith('image/'):
                    html = '<img src="{}" style="max-width:50%;height:auto;"/>'.format(url)
                elif ctype.startswith('audio/'):
                    html = '<audio preload="auto" controls="controls"><source src="{}" type="{}"/></audio>'.format(url, ctype or 'audio/mpeg')
                elif ctype.startswith('video/'):
                    html = '<video controls style="max-width:50%"><source src="{}" type="{}"/></video>'.format(url, ctype or 'video/mp4')
                else:
                    html = '<a href="{}" target="_blank" rel="noopener">Download media</a>'.format(url)
            rec.media_widget = html

    @api.model
    def _reference_models(self):
        return [(model.model, model.name) for model in self.env['ir.model'].sudo().search([])]

    @api.depends('res_model', 'res_id')
    def _compute_ref(self):
        for rec in self:
            if rec.res_model and rec.res_id:
                try:
                    rec.ref = self.env[rec.res_model].browse(rec.res_id)
                except Exception:
                    rec.ref = False
            else:
                rec.ref = False

    @api.depends('status', 'sender_user')
    def _compute_direction(self):
        """Determine message direction based on status or sender_user.
        - If sender_user is set, it's outgoing (we sent it)
        - If status is 'received', it's incoming
        - Otherwise determine by checking if from_number is ours
        """
        for rec in self:
            if rec.sender_user:
                rec.direction = 'outgoing'
            elif rec.status == 'received':
                rec.direction = 'incoming'
            else:
                # Check if from_number matches any of our numbers
                our_numbers = self.env['connect.number'].search([]).mapped('phone_number')
                if rec.from_number in our_numbers:
                    rec.direction = 'outgoing'
                else:
                    rec.direction = 'incoming'

    @api.depends('direction')
    def _compute_direction_display(self):
        """Display direction with icon (no colors)."""
        for rec in self:
            if rec.direction == 'incoming':
                rec.direction_display = '<span class="fa fa-arrow-down p-1"/>'
            elif rec.direction == 'outgoing':
                rec.direction_display = '<span class="fa fa-arrow-up p-1"/>'
            else:
                rec.direction_display = ''

    @api.depends('status')
    def _compute_status_display(self):
        """Icon for message status (no colors)."""
        for rec in self:
            s = (rec.status or '').lower()
            icon = ''
            if s in ('sent', 'sending'):
                icon = 'paper-plane'
            elif s in ('delivered', 'read', 'received'):
                icon = 'check-circle'
            elif s in ('queued', 'deferred'):
                icon = 'clock-o'
            elif s in ('failed', 'undeliverable', 'error'):
                icon = 'times-circle'
            elif s in ('draft',):
                icon = 'pencil-square-o'
            elif not s:
                icon = ''
            rec.status_display = f'<span class="fa fa-{icon}"/>' if icon else ''

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
                record.message_type = 'mms' if record.num_media > 0 else 'sms'
        return res

    @api.depends('from_number', 'create_date', 'message_type')
    def _compute_name(self):
        for record in self:
            if record.create_date:
                formatted_number = self._format_phone_number(record.from_number)
                record.name = f"{record.message_type} from {formatted_number} on {record.create_date.strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                record.name = f"New {record.message_type}"

    def transcribe_voice_message(self, openai_api_key, media_url):
        result = {}
        try:
            client = openai.OpenAI(api_key=openai_api_key)
            response = requests.get(media_url, stream=True)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                temp_file_path = temp_file.name
            with open(temp_file_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file,
                    response_format='verbose_json', timestamp_granularities=["segment"])
            segments = ''
            for s in transcript.segments:
                segments += '{}\n'.format(s.text)
            result['body'] = segments.strip()
        except Exception as e:
            logger.exception('Transcribe error:')
            result['transcription_error'] = str(e)
        finally:
            return result

    def get_receive_message_values(self, params):
        values = {
            'message_sid': params.get('MessageSid'),
            'from_number': params.get('From'),
            'to_number': params.get('To'),
            'body': params.get('Body'),
            'num_media': int(params.get('NumMedia', 0)),
            'from_city': params.get('FromCity'),
            'from_state': params.get('FromState'),
            'from_zip': params.get('FromZip'),
            'from_country': params.get('FromCountry'),
            'account_sid': params.get('AccountSid'),
            'messaging_service_sid': params.get('MessagingServiceSid'),
            'status': params.get('SmsStatus'),
            'media_content_type': params.get('MediaContentType0'),
            'media_url': params.get('MediaUrl0'),
        }
        if params.get('MessageType') == 'audio':
            transcript_voice_message = self.env['connect.settings'].sudo().get_param('transcript_voice_message')
            openai_key = self.env['connect.settings'].sudo().get_param('openai_api_key')
            if transcript_voice_message and openai_key:
                transcription = self.transcribe_voice_message(openai_key, params.get('MediaUrl0'))
                values.update(transcription)
            elif transcript_voice_message and not openai_key:
                logger.warning('OpenAI key is not set! Transcription will not be available.')
        return values

    @api.model
    def receive(self, params):
        if not self.env['oduist.license'].check_license('connect', silent=True):
            return str(MessagingResponse())
        try:
            if params.get('AccountSid') != self.env['connect.settings'].get_param('account_sid'):
                logger.warning("Received Twilio SMS webhook with incorrect AccountSid")
                return
            if params.get('SmsStatus') == 'received':
                # Create SMS message record
                from_number = params.get('From')
                to_number = params.get('To')
                values = self.get_receive_message_values(params)
                # Media handling (image, audio, video)
                try:
                    if int(params.get('NumMedia', '0') or 0) > 0:
                        values.update({
                            'media_url': params.get('MediaUrl0'),
                            'media_content_type': params.get('MediaContentType0'),
                        })
                except Exception:
                    pass

                partner = self.env['res.partner'].get_partner_by_number(from_number)
                if partner:
                    values.update({'partner': partner.id})
                # Determine parent and target using OriginalRepliedMessageSid if provided
                original_sid = (
                    params.get('OriginalRepliedMessageSid')
                    or params.get('originalrepliedmessagesid')
                    or next((params[k] for k in params.keys() if str(k).lower() == 'originalrepliedmessagesid'), None)
                )
                parent_msg = False
                if original_sid:
                    parent_msg = self.env['connect.message'].search([('message_sid', '=', original_sid)], limit=1)
                last_message = False
                if not parent_msg:
                    last_message = self.env['connect.message'].search([
                        ('from_number', '=', to_number), ('to_number', '=', from_number)
                    ], order='create_date desc', limit=1)
                target_msg = parent_msg or last_message
                # Validate that the target record still exists; otherwise, skip linking and let destination handler create new
                valid_target = False
                if target_msg and target_msg.res_model and target_msg.res_id:
                    target_rec = self.env[target_msg.res_model].sudo().browse(target_msg.res_id)
                    if target_rec.exists():
                        values.update({
                            'res_model': target_msg.res_model,
                            'res_id': target_msg.res_id,
                        })
                        valid_target = True
                    else:
                        logger.warning(
                            'Target record %s(%s) does not exist anymore; will create a new destination record instead',
                            target_msg.res_model, target_msg.res_id
                        )
                        # Invalidate target to avoid chatter posting on a deleted record
                        target_msg = False
                if parent_msg:
                    values.update({'parent_message': parent_msg.id})
                message = self.env['connect.message'].sudo().create(values)
                # Message destination handling when not previous messages found.
                if not target_msg:
                    target_msg = message
                    valid_target = True
                    config = self.env['connect.message_configuration'].search([('number.phone_number', '=', to_number)], limit=1)
                    dest_model = (config.destination if config and config.destination else 'res.partner')
                    defaults = {}
                    if config and config.default_values:
                        try:
                            defaults = dict(ast.literal_eval(config.default_values or '{}'))
                        except Exception as e:
                            logger.error('Invalid default data: %s\n%s', config.default_values, e)
                    if dest_model in self.env:
                        try:
                            new_rec = self.env[dest_model].with_context(mail_create_nosubscribe=True).sudo().create_record_from_message(message, default_values=defaults)
                            target_msg.write({
                                'res_model': dest_model,
                                'res_id': new_rec.id,
                            })
                        except Exception as e:
                            logger.warning('create_record_from_message failed for %s: %s', dest_model, e)
                    else:
                        logger.warning('Destination model %s not found', dest_model)
                # Add message to chatter at the target record when available and valid
                if valid_target and target_msg and target_msg.res_model and target_msg.res_id:
                    obj = self.env[target_msg.res_model].with_user(SUPERUSER_ID).browse(target_msg.res_id)
                    # Double-check existence to be safe in concurrent delete scenarios
                    if obj.exists() and hasattr(obj, 'message_post'):
                        body = Markup(f"<div class='d-flex flex-row px-1'>"
                                f"<span class='px-1'>{values.get('body')}</span></div>")
                        if message.media_url:
                            body = Markup(f"<div class='d-flex flex-row'>"
                                          f"<span class='px-1'>{values.get('body')}</span>"
                                          f"<br/>{message.media_widget}</div>")

                        # Post as a comment to notify subscribed followers similar to incoming mail
                        mt_note = self.env.ref('mail.mt_note').id
                        kwargs = {
                            'body': body,
                            'subtype_id': mt_note,
                            'message_type': message.message_type
                        }
                        if partner:
                            kwargs.update({'author_id': partner.id})
                        chatter = obj.with_context(mail_create_nosubscribe=True).message_post(**kwargs)
                        chatter.connect_message = message
                        # Let Odoo generate notifications for followers automatically (no manual mail.notification)
                        self.env['connect.settings'].connect_reload_view(target_msg.res_model)
            else:
                # Update message status
                logger.info("Received Update Twilio SMS webhook data:\n%s", params)
                message = self.env['connect.message'].sudo().search([('message_sid', '=', params.get('MessageSid'))])
                message.update({'status': params.get('SmsStatus')})
                if params.get('SmsStatus') == 'failed':
                    message.update({
                        'error_code': params.get('ErrorCode'),
                        'error_message': params.get('ErrorMessage'),
                        'has_error': True,
                    })
        except Exception as e:
            logger.error(f"Error handling incoming SMS: {e}")
        return str(MessagingResponse())  # Return empty TwiML response, i.e. no reply.

    def send(self, recipient, body, res_id=None, res_model=None, outgoing_callerid=None):
        self.env['oduist.license'].check_license('connect', silent=False)
        sender_user = self.env.user
        message_data = {
            'message_type': 'sms',
            'to_number': recipient,
            'body': body,
            'sender_user': sender_user.id,
            'res_id': res_id,
            'res_model': res_model,
            'status': 'sent'
        }
        if outgoing_callerid:
            sender = outgoing_callerid
        else:
            number = sender_user.connect_user.outgoing_callerid
            # Check if user have a number
            if not number:
                raise ValidationError('You dont have an outgoing callerid number!')
            sender = number.number
        message = self.client_send(recipient, sender, body)
        if not message:
            raise ValidationError('Unexpected error! Contact admin or maintainer!')
        # Create message record
        partner = self.env['res.partner'].get_partner_by_number(recipient)
        message_data.update({
            'account_sid': message.account_sid,
            'from_number': sender,
            'partner': partner.id,
            'messaging_service_sid': message.messaging_service_sid,
            'num_media': message.num_media,
            'error_code': message.error_code,
            'error_message': message.error_message,
            'message_sid': message.sid,
        })
        message = self.env['connect.message'].sudo().create(message_data)

        # Add message to chatter
        if res_model and res_id:
            mt_note = self.env.ref('mail.mt_note').id
            obj = self.env[res_model].with_user(SUPERUSER_ID).browse(res_id)
            if hasattr(obj, 'message_post'):
                chat_body = Markup(body)
                kwargs = {
                    'body': chat_body,
                    'subtype_id': mt_note,
                    'message_type': message.message_type
                }
                kwargs.update({'author_id': sender_user.partner_id.id})
                chatter = obj.with_context(mail_create_nosubscribe=True).message_post(**kwargs)
                mail_notification_values = [{
                    'author_id': chatter.author_id.id,
                    'mail_message_id': chatter.id,
                    'res_partner_id': chatter.author_id.id,
                    'sms_number': sender,
                    'notification_type': message.message_type,
                    'is_read': True,
                    'notification_status': 'ready',
                }]
                self.env['mail.notification'].sudo().create(mail_notification_values)
                self.env['connect.settings'].connect_reload_view(res_model)

    def client_send(self, recipient, sender, body):
        api_url = self.env['connect.settings'].get_param('api_url')
        status_callback_url = urljoin(api_url, 'twilio/webhook/message_status')
        try:
            # Messaging is only supported in the US region.
            client = self.env['connect.settings'].get_client(region=False)
            # Send message to twilio
            message = client.messages.create(
                to=recipient,
                from_=sender,
                body=body,
                status_callback=status_callback_url,
            )
            if message.error_code:
                return False
            logger.info('Message to %s is sent.', recipient)
            return message
        except Exception as e:
            logger.exception(e)
            return False

    def action_retry(self):
        for rec in self:
            if rec.status != 'failed':
                continue
            try:
                # Use original sender number if available; send() will use it directly
                self.env['connect.message'].send(
                    recipient=rec.to_number,
                    body=rec.body or '',
                    res_id=rec.res_id or None,
                    res_model=rec.res_model or None,
                    outgoing_callerid=rec.from_number or None,
                )
            except ValidationError:
                raise
            except Exception as e:
                logger.exception('Retry send failed for message %s: %s', rec.id, e)
        return True

    @api.model
    def update_message_status(self, data: dict):
        """Update connect.message status from Twilio status callback payload.
        Expected keys: SmsSid/MessageSid and SmsStatus/MessageStatus.
        """
        sid = data.get('SmsSid') or data.get('MessageSid')
        status = data.get('SmsStatus') or data.get('MessageStatus')
        if not sid:
            logger.warning('Message status callback without SID: %s', data)
            return True
        try:
            message = self.env['connect.message'].search([('message_sid', '=', sid)], limit=1)
            if not message:
                logger.info('Message not found for SID %s', sid)
                return True
            vals = {'status': status} if status else {}
            connect_user = self.env.ref("connect.user_connect_webhook")
            connect_partner = connect_user.partner_id
            if (status or '').lower() == 'failed':
                # Some callbacks include error details
                code = data.get('ErrorCode')
                msg = data.get('ErrorMessage')
                if code:
                    vals['error_code'] = code
                if msg:
                    vals['error_message'] = msg
                    vals['has_error'] = True
                if message.res_model and message.res_id:
                    chatter_message = 'Failed to send this SMS message'
                    self.chatter_post(message.res_model, message.res_id, connect_partner.id, chatter_message)
            elif (status or '').lower() == 'delivered' and message.res_model and message.res_id:
                chatter_message = 'SMS message is delivered.'
                self.chatter_post(message.res_model, message.res_id, connect_partner.id, chatter_message)
            elif (status or '').lower() ==  'undelivered' and message.res_model and message.res_id:
                chatter_message = ('Message is undelivered.')
                self.chatter_post(message.res_model, message.res_id, connect_partner.id, chatter_message)
            if vals:
                message.write(vals)
        except Exception as e:
            logger.warning('Failed to update message status for %s: %s', sid, e)
        return True

    def chatter_post(self, res_model, res_id, author, body):
        try:
            mt_note = self.env.ref('mail.mt_note').id
            obj = self.env[res_model].browse(res_id)
            if hasattr(obj, 'message_post'):
                chatter = obj.sudo().with_context(mail_create_nosubscribe=True).message_post(
                    body=body,
                    subtype_id=mt_note,
                    message_type='sms',
                    author_id=author,
                )
                self.env['mail.notification'].sudo().create([{
                    'author_id': chatter.author_id.id,
                    'mail_message_id': chatter.id,
                    'res_partner_id': chatter.author_id.id,
                    #'sms_number': self.number, # NO number field.
                    'notification_type': 'sms',
                    'is_read': True,
                    'notification_status': 'ready',
                }])
                self.env['connect.settings'].connect_reload_view(res_model)
        except Exception as e:
            logger.warning('Failed to post SMS chatter message on %s,%s: %s', res_model, res_id, e)
