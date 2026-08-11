# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, release


class DiscussChannelMember(models.Model):
    _inherit = (
        'discuss.channel.member'
        if release.version_info[0] >= 17
        else 'mail.channel.partner'
    )

    @api.autovacuum
    def _gc_unpin_connect_channels(self):
        """Unpin read connect_messages channels idle >1 day to keep sidebars clean."""
        one_day_ago = fields.Datetime.now() - timedelta(days=1)
        if release.version_info[0] < 17:
            members = self.search([
                ('is_pinned', '=', True),
                ('channel_id.channel_type', '=', 'connect_messages'),
                ('last_interest_dt', '<', one_day_ago),
            ], limit=1000)
            to_unpin = members.filtered(
                lambda m: m.channel_id.message_unread_counter == 0)
            to_unpin.write({'is_pinned': False})
            for member in to_unpin:
                self.env['bus.bus'].sudo()._sendone(
                    member.partner_id,
                    'mail.channel/unpin',
                    {'id': member.channel_id.id},
                )
            return
        members = self.search([
            ('is_pinned', '=', True),
            ('channel_id.channel_type', '=', 'connect_messages'),
            ('last_seen_dt', '<', one_day_ago),
        ], limit=1000)
        to_unpin = members.filtered(lambda m: m.message_unread_counter == 0)
        to_unpin.unpin_dt = fields.Datetime.now()
        for member in to_unpin:
            member._bus_send("discuss.channel/unpin", {"id": member.channel_id.id})
