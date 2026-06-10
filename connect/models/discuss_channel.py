# -*- coding: utf-8 -*-
import base64
import logging
import os
from datetime import timedelta

from markupsafe import Markup

from odoo import api, Command, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext

logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    channel_type = fields.Selection(
        selection_add=[('connect_messages', 'Customer Messages')],
        ondelete={'connect_messages': 'cascade'},
    )
    # The customer this conversation belongs to (one channel per partner).
    connect_partner_id = fields.Many2one(
        'res.partner', string='Customer', index='btree_not_null')
    # Phone number we last spoke to the customer on; default reply target.
    connect_number = fields.Char(string='Customer Number')
    # Messaging provider used to reach this customer ('sms' or 'whatsapp').
    connect_channel_provider = fields.Char(string='Channel Provider', default='sms')
    # WhatsApp 24h session window (per Twilio/Meta), WhatsApp messages only.
    connect_last_inbound_whatsapp_id = fields.Many2one('mail.message')
    connect_whatsapp_valid_until = fields.Datetime(
        compute='_compute_connect_whatsapp_window')
    connect_whatsapp_window_open = fields.Boolean(
        compute='_compute_connect_whatsapp_window')

    @api.depends('connect_last_inbound_whatsapp_id',
                 'connect_last_inbound_whatsapp_id.create_date')
    def _compute_connect_whatsapp_window(self):
        now = fields.Datetime.now()
        for channel in self:
            last = channel.connect_last_inbound_whatsapp_id
            if channel.channel_type == 'connect_messages' and last:
                channel.connect_whatsapp_valid_until = last.create_date + timedelta(hours=24)
                channel.connect_whatsapp_window_open = channel.connect_whatsapp_valid_until > now
            else:
                channel.connect_whatsapp_valid_until = False
                channel.connect_whatsapp_window_open = False

    @api.model
    def _connect_agent_partners(self):
        admin_group = self.env.ref('connect.group_connect_admin', raise_if_not_found=False)
        user_group = self.env.ref('connect.group_connect_user', raise_if_not_found=False)
        groups = (admin_group | user_group).filtered(bool)
        if not groups:
            return self.env['res.partner']
        users = self.env['res.users'].sudo().search([('all_group_ids', 'in', groups.ids)])
        return users.partner_id

    @staticmethod
    def _connect_parse_number(number):
        """Strip provider prefix and return (clean_number, provider)."""
        if (number or '').startswith('whatsapp:'):
            return number[len('whatsapp:'):], 'whatsapp'
        return number or '', 'sms'

    def _get_connect_channel(self, partner=False, number=False, create_if_not_found=False):
        """Find-or-create a connect_messages channel.

        When partner is given the channel is keyed on the partner.
        When only number is given (no partner) the channel is keyed on the phone number.
        Provider prefix (e.g. 'whatsapp:') is stripped from the stored number.
        """
        clean_number, provider = self._connect_parse_number(number)
        if partner:
            channel = self.sudo().search([
                ('channel_type', '=', 'connect_messages'),
                ('connect_partner_id', '=', partner.id),
            ], limit=1)
            if channel:
                if clean_number and channel.connect_number != clean_number:
                    channel.connect_number = clean_number
                return channel
            if not create_if_not_found:
                return self.browse()
            members = self._connect_agent_partners() | partner
            return self.sudo().with_context(mail_create_nosubscribe=True).create({
                'name': partner.display_name,
                'channel_type': 'connect_messages',
                'connect_partner_id': partner.id,
                'connect_number': clean_number or partner.phone_sanitized,
                'connect_channel_provider': provider,
                'channel_member_ids': [Command.create({'partner_id': p.id}) for p in members],
            })
        elif clean_number:
            # Phone-number-only channel: no partner yet, keyed on the clean number.
            channel = self.sudo().search([
                ('channel_type', '=', 'connect_messages'),
                ('connect_partner_id', '=', False),
                ('connect_number', '=', clean_number),
            ], limit=1)
            if channel:
                return channel
            if not create_if_not_found:
                return self.browse()
            members = self._connect_agent_partners()
            return self.sudo().with_context(mail_create_nosubscribe=True).create({
                'name': clean_number,
                'channel_type': 'connect_messages',
                'connect_partner_id': False,
                'connect_number': clean_number,
                'connect_channel_provider': provider,
                'channel_member_ids': [Command.create({'partner_id': p.id}) for p in members],
            })
        return self.browse()

    def connect_create_partner(self, partner_name=None):
        """Create a contact for a phone-number-only channel and link it to the channel."""
        self.ensure_one()
        if self.channel_type != 'connect_messages':
            raise ValidationError('Not a Connect Messages channel')
        if self.connect_partner_id:
            raise ValidationError('Channel already has a contact')
        number = self.connect_number
        if not number:
            raise ValidationError('Channel has no phone number')
        img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               'static', 'src', 'images', 'default_contact.jpg')
        default_image = False
        if os.path.exists(img_path):
            with open(img_path, 'rb') as f:
                default_image = base64.b64encode(f.read())
        partner = self.env['res.partner'].sudo().create({
            'name': partner_name or number,
            'phone': number,
            'image_1920': default_image or False,
        })
        self._connect_link_partner(partner)
        return {'partner_id': partner.id, 'partner_name': partner.display_name}

    def _connect_link_partner(self, partner):
        """Link a newly-created partner to this phone-number-only channel."""
        self.ensure_one()
        self.sudo().write({
            'connect_partner_id': partner.id,
            'name': partner.display_name,
        })
        if partner not in self.channel_member_ids.partner_id:
            self.sudo().write({
                'channel_member_ids': [Command.create({'partner_id': partner.id})]
            })
        # Back-fill partner on existing connect.message records for this number.
        self.env['connect.message'].sudo().search([
            ('from_number', '=', self.connect_number),
            ('partner', '=', False),
        ]).write({'partner': partner.id})

    def _connect_post_inbound(self, connect_message):
        """Mirror an incoming connect.message into this channel as a mail.message."""
        self.ensure_one()
        partner = connect_message.partner
        body_txt = connect_message.body or ''
        if connect_message.media_url:
            body = Markup("<div class='d-flex flex-column'>"
                          "<span>{}</span>{}</div>").format(
                              body_txt, connect_message.media_widget)
        else:
            body = Markup("<span>{}</span>").format(body_txt)
        # Author the message as the customer's partner when known. For an unknown
        # number leave author_id empty and surface the phone number via email_from
        # so it shows as the sender name (instead of OdooBot/partner_root).
        if partner:
            author_vals = {'author_id': partner.id}
        else:
            author_vals = {
                'author_id': False,
                'email_from': self.connect_number or connect_message.from_number,
            }
        msg = self.sudo().with_context(connect_mirror=True).message_post(
            body=body,
            message_type='connect_message',
            subtype_xmlid='mail.mt_comment',
            **author_vals,
        )
        write_vals = {'channel_id': self.id}
        if not connect_message.mail_message_id:
            write_vals['mail_message_id'] = msg.id
        connect_message.write(write_vals)
        msg.connect_message = connect_message.id
        if connect_message.message_type == 'WhatsApp':
            self.connect_last_inbound_whatsapp_id = msg.id
        # Surface in agents' sidebars: re-pin for all members on new inbound.
        self.channel_member_ids.filtered(lambda m: not m.is_pinned).write({'unpin_dt': False})
        return msg

    def _get_allowed_message_params(self):
        # Allow the composer to pass provider/sender through the post route.
        return super()._get_allowed_message_params() | {
            'connect_provider', 'connect_sender_id'}

    def message_post(self, *args, **kwargs):
        connect_provider = kwargs.pop('connect_provider', None)
        connect_sender_id = kwargs.pop('connect_sender_id', None)
        is_outbound = (
            self.channel_type == 'connect_messages'
            and kwargs.get('message_type') == 'connect_message'
            and kwargs.get('subtype_xmlid') != 'mail.mt_note'
            and not self.env.context.get('connect_mirror')
        )
        message = super().message_post(*args, **kwargs)
        if is_outbound and message:
            try:
                self._connect_send_outbound(message, connect_provider, connect_sender_id)
            except Exception:
                logger.exception('Connect outbound send failed for channel %s', self.id)
                raise
        return message

    def _connect_recipient(self):
        self.ensure_one()
        if self.connect_number:
            return self.connect_number
        return self.connect_partner_id.phone_sanitized

    def _connect_send_outbound(self, message, provider, sender_id):
        self.ensure_one()
        partner = self.connect_partner_id
        recipient = self._connect_recipient()
        body = html2plaintext(message.body) if message.body else ''
        provider = provider or self.connect_channel_provider or 'sms'
        res_id = partner.id or None
        res_model = 'res.partner' if res_id else None

        # Find the last inbound message so we know which of our Twilio numbers
        # the customer originally messaged — reply from that same line.
        last_inbound = self.env['connect.message'].sudo().search(
            [('channel_id', '=', self.id), ('status', '=', 'received')],
            order='create_date desc', limit=1)

        if provider == 'whatsapp':
            Sender = self.env['connect.whatsapp_sender']
            if sender_id:
                wa_sender = Sender.sudo().browse(int(sender_id))
            elif last_inbound:
                to_num = (last_inbound.to_number or '').replace('whatsapp:', '')
                wa_sender = Sender.sudo().search([('number', '=', to_num)], limit=1)
                if not wa_sender:
                    wa_sender = Sender.get_default_sender(self.env.user)
            else:
                wa_sender = Sender.get_default_sender(self.env.user)
            cmsg = wa_sender.send_whatsapp(
                recipient=recipient, body=body,
                res_model=res_model, res_id=res_id,
                raise_on_error=True, skip_chatter=True)
        else:
            media_urls = self._connect_media_urls(message)
            callerid = sender_id or None
            if not callerid and last_inbound:
                callerid = last_inbound.to_number or None
            cmsg = self.env['connect.message'].send(
                recipient, body, res_id=res_id, res_model=res_model,
                outgoing_callerid=callerid, media_urls=media_urls,
                skip_chatter=True)
        if cmsg:
            cmsg.sudo().write({'mail_message_id': message.id, 'channel_id': self.id})
            message.sudo().connect_message = cmsg.id
        return cmsg

    def _connect_media_urls(self, message):
        urls = []
        base = self.env['connect.settings'].sudo().get_param('api_url') or self.get_base_url()
        for att in message.attachment_ids:
            token = att.sudo().generate_access_token()[0]
            urls.append('%s/web/content/%d?access_token=%s&download=true' % (
                base.rstrip('/'), att.id, token))
        return urls

    def _to_store(self, store, *args, **kwargs):
        super()._to_store(store, *args, **kwargs)
        for channel in self.filtered(lambda c: c.channel_type == 'connect_messages'):
            # add_records_fields (not add) avoids re-entering _to_store recursively.
            store.add_records_fields(channel, {
                'connect_whatsapp_window_open': channel.connect_whatsapp_window_open,
                'connect_whatsapp_valid_until': channel.connect_whatsapp_valid_until,
                'connect_partner_id': channel.connect_partner_id.id or False,
                'connect_number': channel.connect_number,
                'connect_channel_provider': channel.connect_channel_provider or 'sms',
            })
