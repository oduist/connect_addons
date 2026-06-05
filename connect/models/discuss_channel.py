# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import api, Command, fields, models
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
        group = self.env.ref('connect.group_connect_user', raise_if_not_found=False)
        if not group:
            return self.env['res.partner']
        users = self.env['res.users'].sudo().search([('all_group_ids', 'in', group.ids)])
        return users.partner_id

    @api.returns('self')
    def _get_connect_channel(self, partner, number=False, create_if_not_found=False):
        """Find-or-create the single connect_messages channel for a partner."""
        if not partner:
            return self.browse()
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
        channel = self.sudo().with_context(
            mail_create_nosubscribe=True,
        ).create({
            'name': partner.display_name,
            'channel_type': 'connect_messages',
            'connect_partner_id': partner.id,
            'connect_number': number or partner.phone_sanitized,
            'channel_member_ids': [Command.create({'partner_id': p.id}) for p in members],
        })
        return channel
