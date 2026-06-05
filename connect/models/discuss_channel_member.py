# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo import api, models


class DiscussChannelMember(models.Model):
    _inherit = 'discuss.channel.member'

    @api.autovacuum
    def _gc_unpin_connect_channels(self):
        """Unpin read connect_messages channels idle >1 day to keep sidebars clean."""
        one_day_ago = datetime.now() - timedelta(days=1)
        members = self.search([
            ('is_pinned', '=', True),
            ('channel_id.channel_type', '=', 'connect_messages'),
            ('last_seen_dt', '<', one_day_ago),
        ], limit=1000)
        to_unpin = members.filtered(lambda m: m.message_unread_counter == 0)
        to_unpin.unpin_dt = datetime.now()
        for member in to_unpin:
            member._bus_send("discuss.channel/unpin", {"id": member.channel_id.id})
