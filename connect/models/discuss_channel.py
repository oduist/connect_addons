# -*- coding: utf-8 -*-
import logging
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

    def _get_connect_channel(self, partner=False, number=False, create_if_not_found=False):
        """Find-or-create a connect_messages channel.

        When partner is given the channel is keyed on the partner.
        When only number is given (no partner) the channel is keyed on the phone number.
        """
        if partner:
            channel = self.sudo().search([
                ('channel_type', '=', 'connect_messages'),
                ('connect_partner_id', '=', partner.id),
            ], limit=1)
            if channel:
                if number and channel.connect_number != number:
                    channel.connect_number = number
                return channel
            if not create_if_not_found:
                return self.browse()
            members = self._connect_agent_partners() | partner
            return self.sudo().with_context(mail_create_nosubscribe=True).create({
                'name': partner.display_name,
                'channel_type': 'connect_messages',
                'connect_partner_id': partner.id,
                'connect_number': number or partner.phone_sanitized,
                'channel_member_ids': [Command.create({'partner_id': p.id}) for p in members],
            })
        elif number:
            # Phone-number-only channel: no partner yet, keyed on the number.
            channel = self.sudo().search([
                ('channel_type', '=', 'connect_messages'),
                ('connect_partner_id', '=', False),
                ('connect_number', '=', number),
            ], limit=1)
            if channel:
                return channel
            if not create_if_not_found:
                return self.browse()
            members = self._connect_agent_partners()
            return self.sudo().with_context(mail_create_nosubscribe=True).create({
                'name': number,
                'channel_type': 'connect_messages',
                'connect_partner_id': False,
                'connect_number': number,
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
        partner = self.env['res.partner'].sudo().create({
            'name': partner_name or number,
            'phone': number,
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
        author = partner or self.env.ref('base.partner_root')
        body_txt = connect_message.body or ''
        if connect_message.media_url:
            body = Markup("<div class='d-flex flex-column'>"
                          "<span>{}</span>{}</div>").format(
                              body_txt, connect_message.media_widget)
        else:
            body = Markup("<span>{}</span>").format(body_txt)
        msg = self.sudo().with_context(connect_mirror=True).message_post(
            body=body,
            author_id=author.id,
            message_type='connect_message',
            subtype_xmlid='mail.mt_comment',
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
        provider = provider or 'sms'
        if provider == 'whatsapp':
            Sender = self.env['connect.whatsapp_sender']
            sender = Sender.browse(int(sender_id)) if sender_id else Sender.get_default_sender(self.env.user)
            cmsg = sender.send_whatsapp(
                recipient=recipient, body=body,
                res_model='res.partner', res_id=partner.id, raise_on_error=True,
                skip_chatter=True)
        else:
            media_urls = self._connect_media_urls(message)
            cmsg = self.env['connect.message'].send(
                recipient, body, res_id=partner.id, res_model='res.partner',
                outgoing_callerid=sender_id or None, media_urls=media_urls,
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
            })
