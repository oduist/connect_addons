# -*- coding: utf-8 -*-
import base64
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import api, Command, fields, models, release
from odoo.exceptions import ValidationError
from odoo.tools import file_open, html2plaintext

if release.version_info[0] >= 17:
    from odoo.addons.mail.tools.discuss import Store

logger = logging.getLogger(__name__)

CHANNEL_MODEL = 'discuss.channel' if release.version_info[0] >= 17 else 'mail.channel'


class DiscussChannel(models.Model):
    """Customer messaging channel shared by Odoo 15 and modern Discuss.

    Odoo 15 still calls the model ``mail.channel`` and serializes it through
    ``channel_info``. Odoo 17+ calls it ``discuss.channel`` and uses ``Store``.
    The feature logic remains common; only the transport/member APIs branch.
    """

    _inherit = CHANNEL_MODEL

    channel_type = fields.Selection(
        selection_add=[('connect_messages', 'Customer Messages')],
        ondelete={'connect_messages': 'cascade'},
    )
    connect_partner_id = fields.Many2one(
        'res.partner', string='Customer', index=True)
    connect_number = fields.Char(string='Customer Number')
    connect_channel_provider = fields.Char(
        string='Channel Provider', default='sms')
    connect_last_inbound_whatsapp_id = fields.Many2one('mail.message')
    connect_whatsapp_valid_until = fields.Datetime(
        compute='_compute_connect_whatsapp_window')
    connect_whatsapp_window_open = fields.Boolean(
        compute='_compute_connect_whatsapp_window')

    @api.depends(
        'connect_last_inbound_whatsapp_id',
        'connect_last_inbound_whatsapp_id.create_date',
    )
    def _compute_connect_whatsapp_window(self):
        now = fields.Datetime.now()
        for channel in self:
            last = channel.connect_last_inbound_whatsapp_id
            if channel.channel_type == 'connect_messages' and last:
                channel.connect_whatsapp_valid_until = (
                    last.create_date + timedelta(hours=24))
                channel.connect_whatsapp_window_open = (
                    channel.connect_whatsapp_valid_until > now)
            else:
                channel.connect_whatsapp_valid_until = False
                channel.connect_whatsapp_window_open = False

    @api.model
    def _connect_agent_partners(self):
        admin_group = self.env.ref(
            'connect.group_connect_admin', raise_if_not_found=False)
        user_group = self.env.ref(
            'connect.group_connect_user', raise_if_not_found=False)
        groups = (admin_group | user_group).filtered(bool)
        if not groups:
            return self.env['res.partner']
        group_field = 'all_group_ids' if release.version_info[0] >= 18 else 'groups_id'
        users = self.env['res.users'].sudo().search([
            (group_field, 'in', groups.ids),
        ])
        return users.partner_id

    @staticmethod
    def _connect_parse_number(number):
        if (number or '').startswith('whatsapp:'):
            return number[len('whatsapp:'):], 'whatsapp'
        return number or '', 'sms'

    @api.model
    def _connect_member_create_values(self, members):
        if release.version_info[0] >= 17:
            return {
                'channel_member_ids': [
                    Command.create({'partner_id': partner.id})
                    for partner in members
                ],
            }
        # Odoo 15's ``mail.channel.create`` expands command 6 incorrectly into
        # a nested list before de-duplicating the partner IDs.  Link commands
        # are the supported equivalent for this legacy API.
        return {
            'channel_partner_ids': [
                Command.link(partner_id) for partner_id in members.ids
            ],
        }

    def _connect_member_partners(self):
        self.ensure_one()
        if release.version_info[0] >= 17:
            return self.channel_member_ids.partner_id
        return self.channel_last_seen_partner_ids.partner_id

    def _get_connect_channel(
        self, partner=False, number=False, provider='sms',
        create_if_not_found=False,
    ):
        clean_number = self._connect_parse_number(number)[0]
        if partner:
            channel = self.sudo().search([
                ('channel_type', '=', 'connect_messages'),
                ('connect_partner_id', '=', partner.id),
            ], limit=1)
            if channel:
                vals = {}
                if clean_number and channel.connect_number != clean_number:
                    vals['connect_number'] = clean_number
                if provider and channel.connect_channel_provider != provider:
                    vals['connect_channel_provider'] = provider
                if vals:
                    channel.write(vals)
                return channel
            if not create_if_not_found:
                return self.browse()
            members = self._connect_agent_partners() | partner
            vals = {
                'name': partner.display_name,
                'channel_type': 'connect_messages',
                'connect_partner_id': partner.id,
                'connect_number': clean_number or partner.phone_sanitized,
                'connect_channel_provider': provider,
            }
            if release.version_info[0] < 17:
                vals['public'] = 'private'
            vals.update(self._connect_member_create_values(members))
            return self.sudo().with_context(mail_create_nosubscribe=True).create(vals)
        if clean_number:
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
            vals = {
                'name': clean_number,
                'channel_type': 'connect_messages',
                'connect_partner_id': False,
                'connect_number': clean_number,
                'connect_channel_provider': provider,
            }
            if release.version_info[0] < 17:
                vals['public'] = 'private'
            vals.update(self._connect_member_create_values(members))
            return self.sudo().with_context(mail_create_nosubscribe=True).create(vals)
        return self.browse()

    def connect_create_partner(self, partner_name=None):
        self.ensure_one()
        if self.channel_type != 'connect_messages':
            raise ValidationError('Not a Connect Messages channel')
        if self.connect_partner_id:
            raise ValidationError('Channel already has a contact')
        if not self.connect_number:
            raise ValidationError('Channel has no phone number')
        default_image = False
        try:
            with file_open('mail/static/src/img/smiley/avatar.jpg', 'rb') as stream:
                default_image = base64.b64encode(stream.read())
        except Exception:
            logger.warning('Could not read default contact avatar', exc_info=True)
        partner = self.env['res.partner'].sudo().create({
            'name': partner_name or self.connect_number,
            'phone': self.connect_number,
            'image_1920': default_image or False,
        })
        self._connect_link_partner(partner)
        return {'partner_id': partner.id, 'partner_name': partner.display_name}

    def _connect_link_partner(self, partner):
        self.ensure_one()
        self.sudo().write({
            'connect_partner_id': partner.id,
            'name': partner.display_name,
        })
        if partner not in self._connect_member_partners():
            if release.version_info[0] >= 17:
                self.sudo().write({
                    'channel_member_ids': [
                        Command.create({'partner_id': partner.id}),
                    ],
                })
            else:
                self.sudo().write({
                    'channel_partner_ids': [Command.link(partner.id)],
                })
        self.env['connect.message'].sudo().search([
            ('from_number', '=', self.connect_number),
            ('partner', '=', False),
        ]).write({'partner': partner.id})

    def _connect_message_body(self, connect_message):
        body_text = connect_message.body or ''
        if connect_message.media_url:
            return Markup(
                "<div class='d-flex flex-column'><span>{}</span>{}</div>"
            ).format(body_text, connect_message.media_widget)
        return Markup('<span>{}</span>').format(body_text)

    def _connect_post_inbound(self, connect_message, parent_id=False):
        self.ensure_one()
        partner = connect_message.partner
        if partner:
            author_vals = {'author_id': partner.id}
        else:
            author_vals = {
                'author_id': False,
                'email_from': self.connect_number or connect_message.from_number,
            }
        post_kwargs = {
            'body': self._connect_message_body(connect_message),
            'message_type': 'connect_message',
            'subtype_xmlid': 'mail.mt_comment',
            **author_vals,
        }
        if parent_id:
            post_kwargs['parent_id'] = parent_id
        message = self.sudo().with_context(connect_mirror=True).message_post(
            **post_kwargs)
        connect_message.write({
            'channel_id': self.id,
            'channel_message_id': message.id,
        })
        message.connect_message = connect_message.id
        if connect_message.message_type == 'whatsapp':
            self.connect_last_inbound_whatsapp_id = message.id
        self._connect_resurface()
        return message

    def _connect_post_outbound(self, connect_message):
        self.ensure_one()
        author = (
            connect_message.sender_user.partner_id
            or self.env.user.partner_id
        )
        message = self.sudo().with_context(connect_mirror=True).message_post(
            body=self._connect_message_body(connect_message),
            message_type='connect_message',
            subtype_xmlid='mail.mt_comment',
            author_id=author.id,
        )
        connect_message.write({
            'channel_id': self.id,
            'channel_message_id': message.id,
        })
        message.connect_message = connect_message.id
        self._connect_resurface()
        return message

    def _connect_resurface(self):
        self.ensure_one()
        if release.version_info[0] >= 17:
            archived = self.channel_member_ids.filtered(lambda member: not member.is_pinned)
            if not archived:
                return
            archived.write({'unpin_dt': False})
            for member in archived:
                user = member.partner_id.user_ids[:1]
                if user:
                    Store(bus_channel=user).add(self.with_user(user)).bus_send()
            return

        archived = self.channel_last_seen_partner_ids.filtered(
            lambda member: not member.is_pinned)
        if not archived:
            return
        archived.write({
            'is_pinned': True,
            'last_interest_dt': fields.Datetime.now(),
        })
        for member in archived:
            user = member.partner_id.user_ids[:1]
            if user:
                info = self.with_user(user).sudo().channel_info()[0]
                self.env['bus.bus'].sudo()._sendone(
                    member.partner_id,
                    'mail.channel/legacy_insert',
                    info,
                )

    if release.version_info[0] >= 17:
        def _get_allowed_message_params(self):
            return super()._get_allowed_message_params() | {
                'connect_provider', 'connect_sender_id',
            }

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
            self._connect_send_outbound(
                message, connect_provider, connect_sender_id)
        return message

    def _connect_recipient(self):
        self.ensure_one()
        return self.connect_number or self.connect_partner_id.phone_sanitized

    def _connect_send_outbound(self, message, provider, sender_id):
        self.ensure_one()
        partner = self.connect_partner_id
        recipient = self._connect_recipient()
        if not recipient:
            raise ValidationError('Channel has no recipient phone number')
        body = html2plaintext(message.body) if message.body else ''
        provider = provider or self.connect_channel_provider or 'sms'
        res_id = partner.id or None
        res_model = 'res.partner' if res_id else None
        last_inbound = self.env['connect.message'].sudo().search([
            ('channel_id', '=', self.id),
            ('status', '=', 'received'),
        ], order='create_date desc', limit=1)
        if provider == 'whatsapp':
            sender_model = self.env['connect.whatsapp_sender']
            if sender_id:
                whatsapp_sender = sender_model.sudo().browse(int(sender_id))
            elif last_inbound:
                whatsapp_sender = sender_model.sudo().search([
                    ('number', '=', last_inbound.to_number),
                ], limit=1)
                if not whatsapp_sender:
                    whatsapp_sender = sender_model.get_default_sender(self.env.user)
            else:
                whatsapp_sender = sender_model.get_default_sender(self.env.user)
            if not whatsapp_sender:
                raise ValidationError('No WhatsApp sender is configured')
            connect_message = whatsapp_sender.send_whatsapp(
                recipient=recipient,
                body=body,
                res_model=res_model,
                res_id=res_id,
                raise_on_error=True,
                skip_chatter=True,
            )
        else:
            caller_id = sender_id or None
            if not caller_id and last_inbound:
                caller_id = last_inbound.to_number or None
            connect_message = self.env['connect.message'].send(
                recipient,
                body,
                res_id=res_id,
                res_model=res_model,
                outgoing_callerid=caller_id,
                media_urls=self._connect_media_urls(message),
                skip_chatter=True,
            )
        if connect_message:
            connect_message.sudo().write({
                'channel_message_id': message.id,
                'channel_id': self.id,
            })
            message.sudo().connect_message = connect_message.id
        return connect_message

    def _connect_media_urls(self, message):
        urls = []
        base_url = (
            self.env['connect.settings'].sudo().get_param('api_url')
            or self.get_base_url()
        )
        for attachment in message.attachment_ids:
            token = attachment.sudo().generate_access_token()[0]
            urls.append('%s/web/content/%d?access_token=%s&download=true' % (
                base_url.rstrip('/'), attachment.id, token,
            ))
        return urls

    if release.version_info[0] >= 17:
        def _to_store(self, store, *args, **kwargs):
            super()._to_store(store, *args, **kwargs)
            for channel in self.filtered(
                    lambda rec: rec.channel_type == 'connect_messages'):
                store.add_records_fields(channel, {
                    'connect_whatsapp_window_open': (
                        channel.connect_whatsapp_window_open),
                    'connect_whatsapp_valid_until': (
                        channel.connect_whatsapp_valid_until),
                    'connect_partner_id': channel.connect_partner_id.id or False,
                    'connect_number': channel.connect_number,
                    'connect_channel_provider': (
                        channel.connect_channel_provider or 'sms'),
                })
    else:
        def channel_info(self):
            info_list = super().channel_info()
            channels = {channel.id: channel for channel in self}
            for info in info_list:
                channel = channels.get(info['id'])
                if channel and channel.channel_type == 'connect_messages':
                    info.update({
                        'connect_whatsapp_window_open': (
                            channel.connect_whatsapp_window_open),
                        'connect_whatsapp_valid_until': (
                            fields.Datetime.to_string(
                                channel.connect_whatsapp_valid_until)
                            if channel.connect_whatsapp_valid_until else False),
                        'connect_partner_id': (
                            channel.connect_partner_id.id or False),
                        'connect_number': channel.connect_number,
                        'connect_channel_provider': (
                            channel.connect_channel_provider or 'sms'),
                    })
            return info_list
