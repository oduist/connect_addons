# -*- coding: utf-8 -*-
import base64
import logging
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import api, Command, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import file_open, html2plaintext
from odoo.addons.mail.tools.discuss import Store

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
    # Our line this conversation runs on. Stored per channel so that changing
    # the default number, or running several numbers at once, never moves an
    # existing conversation onto another line. Empty on conversations that
    # predate the field: those keep resolving from their last inbound.
    connect_sender_number = fields.Char(string='Sending Line')
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

    def _get_connect_channel(self, partner=False, number=False, provider='sms', create_if_not_found=False):
        """Find-or-create a connect_messages channel.

        When partner is given the channel is keyed on the partner.
        When only number is given (no partner) the channel is keyed on the phone number.
        ``number`` must be a clean E.164 string (no provider prefix).
        ``provider`` ('sms' or 'whatsapp') is passed explicitly by the caller, never parsed
        from the number.
        """
        clean_number = self._connect_parse_number(number)[0]  # defensive strip; provider is passed explicitly
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

    @api.model
    def _connect_normalize_number(self, number):
        """Return a hand-typed number as clean E.164, or '' when unusable.

        Agents type the number themselves in the New SMS dialog, so it arrives
        in any shape ('365-737-9035', '13657379035'). Twilio only accepts
        E.164, and the contact/channel lookups compare against the sanitized
        form, so anything else silently misses and starts a duplicate thread.
        """
        clean_number = (self._connect_parse_number(number)[0] or '').strip()
        if not clean_number:
            return ''
        clean_number = self.env['res.partner']._normalize_phone(clean_number) or ''
        # _normalize_phone falls back to '+<digits>' when it cannot parse, so a
        # too-short result means the input was not a phone number at all.
        if len(re.sub(r'\D', '', clean_number)) < 7:
            return ''
        return clean_number

    @api.model
    def _connect_check_agent(self):
        if not self.env.user.has_group('connect.group_connect_user') \
                and not self.env.user.has_group('connect.group_connect_admin'):
            raise AccessError('Only Connect agents can start SMS conversations.')

    @api.model
    def connect_sms_sender_options(self):
        """Lines the New SMS dialog offers, and which one is preselected.

        The default is always offered even when it is not a Twilio number, so
        a database that sends from a verified caller ID keeps working.
        """
        self._connect_check_agent()
        CallerId = self.env['connect.outgoing_callerid']
        default = CallerId._get_default_number()
        options = [{'number': line.number, 'name': line.friendly_name}
                   for line in CallerId._get_sms_lines()]
        if default and default not in [o['number'] for o in options]:
            options.insert(0, {'number': default, 'name': default})
        return {'default': default, 'options': options}

    @api.model
    def _connect_resolve_sender(self, sender_number=None):
        """Validate a line picked in the dialog, or fall back to the default.

        The number comes from the browser, so it is checked against the lines
        we actually offer rather than handed to Twilio as-is.
        """
        if not sender_number:
            return self.env['connect.message']._get_sender_number()
        allowed = [o['number'] for o in self.connect_sms_sender_options()['options']]
        if sender_number not in allowed:
            raise ValidationError(
                '%s is not one of the numbers this database can send from.'
                % sender_number)
        return sender_number

    def _connect_sms_sender(self):
        """The line this conversation sends from."""
        self.ensure_one()
        if self.connect_sender_number:
            return self.connect_sender_number
        # Conversations older than the field: reply on the number the customer
        # last messaged, exactly as before, so changing the default number
        # never moves them onto another line.
        last_inbound = self.env['connect.message'].sudo().search(
            [('channel_id', '=', self.id), ('status', '=', 'received')],
            order='create_date desc', limit=1)
        return (last_inbound.to_number
                or self.env['connect.message']._get_sender_number())

    @api.model
    def connect_start_sms_channel(self, number, sender_number=None):
        """Start or resume an SMS conversation with the given phone number.

        Called from the Discuss sidebar "New SMS" action.  ``number`` is the
        destination; ``sender_number`` is the line to send from, defaulting to
        the current default.  Finds an existing connect_messages channel for
        this number (or its linked partner) and creates the channel, and the
        contact behind it, when they do not exist yet.  A conversation that
        already exists keeps the line it is already on.  Returns the channel_id
        so the frontend can navigate to it.
        """
        self._connect_check_agent()

        clean_number = self._connect_normalize_number(number)
        if not clean_number:
            raise ValidationError('Please enter a valid phone number.')
        # Resolve the line here, where the dialog can show what went wrong,
        # rather than on the first message: Discuss posts silently and only
        # marks the message with an error icon when the server raises.
        sender_number = self._connect_resolve_sender(sender_number)

        Partner = self.env['res.partner'].sudo()
        partner = Partner.get_partner_by_number(clean_number)
        if not partner:
            # get_partner_by_number gives up when a number is shared across
            # companies; pick one of them over creating a duplicate contact.
            partner = Partner.search([('phone_sanitized', '=', clean_number)], limit=1)
        channel = self._get_connect_channel(
            partner=partner, number=clean_number, provider='sms')
        if partner and not channel:
            # An earlier inbound may have opened a number-only channel for this
            # number; reuse it instead of starting a second conversation.
            channel = self._get_connect_channel(
                number=clean_number, provider='sms')
        if not partner:
            partner = self._connect_create_contact(clean_number)
        if not channel:
            channel = self._get_connect_channel(
                partner=partner, number=clean_number, provider='sms',
                create_if_not_found=True)
            # Only a conversation we start here gets the picked line: resuming
            # one must leave it on the line it has been running on.
            channel.sudo().connect_sender_number = sender_number
        elif not channel.connect_partner_id:
            channel._connect_link_partner(partner)

        # Ensure the current user is a member and the channel is pinned.
        user_partner = self.env.user.partner_id
        if user_partner not in channel.channel_member_ids.partner_id:
            channel.sudo().write({
                'channel_member_ids': [Command.create({'partner_id': user_partner.id})]
            })
        member = channel.channel_member_ids.filtered(
            lambda m: m.partner_id == user_partner)
        if member and not member.is_pinned:
            member.write({'unpin_dt': False})

        return {'channel_id': channel.id}

    @api.model
    def _connect_create_contact(self, number, partner_name=None):
        """Create the contact behind a phone-number-only conversation."""
        # New contacts get Odoo's default mail "smiley" avatar.
        default_image = False
        try:
            with file_open('mail/static/src/img/smiley/avatar.jpg', 'rb') as f:
                default_image = base64.b64encode(f.read())
        except Exception:
            logger.warning('Could not read default contact avatar', exc_info=True)
        return self.env['res.partner'].sudo().create({
            'name': partner_name or number,
            'phone': number,
            'image_1920': default_image or False,
        })

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
        partner = self._connect_create_contact(number, partner_name)
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

    def _connect_post_inbound(self, connect_message, parent_id=False):
        """Mirror an incoming connect.message into this channel as a mail.message.

        ``parent_id`` quotes a parent mail.message (Discuss reply) when the inbound
        is a reply to an earlier message in this thread (see the customer-reply
        screenshot in the feature request).
        """
        self.ensure_one()
        # Answer on the line the customer wrote to. This also stamps the line
        # on conversations older than the field, and on the first inbound of a
        # conversation the customer started.
        if connect_message._provider() == 'sms' and connect_message.to_number \
                and self.connect_sender_number != connect_message.to_number:
            self.sudo().connect_sender_number = connect_message.to_number
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
        post_kwargs = dict(
            body=body,
            message_type='connect_message',
            subtype_xmlid='mail.mt_comment',
            **author_vals,
        )
        if parent_id:
            post_kwargs['parent_id'] = parent_id
        msg = self.sudo().with_context(connect_mirror=True).message_post(**post_kwargs)
        connect_message.write({
            'channel_id': self.id,
            'channel_message_id': msg.id,
        })
        msg.connect_message = connect_message.id
        if connect_message.message_type == 'whatsapp':
            self.connect_last_inbound_whatsapp_id = msg.id
        # Surface in agents' sidebars: re-pin for all members on new inbound.
        self._connect_resurface()
        return msg

    def _connect_post_outbound(self, connect_message):
        """Mirror an outbound connect.message (sent from a record's chatter) into
        this channel, keeping the Discuss thread in sync. Does not re-send — the
        connect_mirror context bypasses the outbound send in ``message_post``.
        """
        self.ensure_one()
        body_txt = connect_message.body or ''
        if connect_message.media_url:
            body = Markup("<div class='d-flex flex-column'>"
                          "<span>{}</span>{}</div>").format(
                              body_txt, connect_message.media_widget)
        else:
            body = Markup("<span>{}</span>").format(body_txt)
        author = connect_message.sender_user.partner_id or self.env.user.partner_id
        msg = self.sudo().with_context(connect_mirror=True).message_post(
            body=body,
            message_type='connect_message',
            subtype_xmlid='mail.mt_comment',
            author_id=author.id,
        )
        connect_message.write({
            'channel_id': self.id,
            'channel_message_id': msg.id,
        })
        msg.connect_message = connect_message.id
        # Surface in agents' sidebars: re-pin for all members on new activity.
        self._connect_resurface()
        return msg

    def _connect_resurface(self):
        """Un-archive the thread for any member who archived (unpinned) it.

        Resets ``unpin_dt`` so the channel re-pins, and pushes the channel to each
        affected member's Discuss sidebar so an archived conversation reappears in
        real time when a new message arrives.
        """
        self.ensure_one()
        archived = self.channel_member_ids.filtered(lambda m: not m.is_pinned)
        if not archived:
            return
        archived.write({'unpin_dt': False})
        for member in archived:
            user = member.partner_id.user_ids[:1]
            if user:
                Store(bus_channel=user).add(self.with_user(user)).bus_send()

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

        if provider == 'whatsapp':
            # Find the last inbound message so we know which of our Twilio
            # numbers the customer originally messaged — reply from that line.
            last_inbound = self.env['connect.message'].sudo().search(
                [('channel_id', '=', self.id), ('status', '=', 'received')],
                order='create_date desc', limit=1)
            Sender = self.env['connect.whatsapp_sender']
            if sender_id:
                wa_sender = Sender.sudo().browse(int(sender_id))
            elif last_inbound:
                to_num = last_inbound.to_number or ''
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
            # Stay on this conversation's own line, so changing the default
            # number never moves conversations already under way.
            callerid = (self._connect_resolve_sender(sender_id) if sender_id
                        else self._connect_sms_sender())
            cmsg = self.env['connect.message'].send(
                recipient, body, res_id=res_id, res_model=res_model,
                outgoing_callerid=callerid, media_urls=media_urls,
                skip_chatter=True)
        if cmsg:
            cmsg.sudo().write({'channel_message_id': message.id, 'channel_id': self.id})
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
