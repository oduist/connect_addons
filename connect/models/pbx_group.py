# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api

logger = logging.getLogger(__name__)


class PbxGroup(models.Model):
    _name = 'connect.pbx_group'
    _description = 'PBX Group'
    _order = 'name'

    name = fields.Char(required=True)
    users = fields.Many2many('connect.user', string='PBX Users')
    user_ids = fields.Many2many(
        'res.users', string='Odoo Users',
        compute='_compute_user_ids', store=True)

    @api.depends('users', 'users.user')
    def _compute_user_ids(self):
        for rec in self:
            rec.user_ids = rec.users.mapped('user')

    def write(self, vals):
        # Track old members before write to recompute their calls too.
        old_user_ids = self.mapped('user_ids')
        res = super().write(vals)
        if 'users' in vals:
            new_user_ids = self.mapped('user_ids')
            affected_user_ids = old_user_ids | new_user_ids
            if affected_user_ids:
                self._recompute_pbx_group_user_ids(affected_user_ids)
        return res

    def _recompute_pbx_group_user_ids(self, user_ids):
        """Recompute pbx_group_user_ids on calls/recordings/channels for affected users."""
        domain = [
            '|',
            ('caller_user', 'in', user_ids.ids),
            ('answered_user', 'in', user_ids.ids),
        ]
        calls = self.env['connect.call'].sudo().search(domain)
        if calls:
            calls._compute_pbx_group_user_ids()
        recordings = self.env['connect.recording'].sudo().search([
            '|',
            ('caller_user', 'in', user_ids.ids),
            ('called_user', 'in', user_ids.ids),
        ])
        if recordings:
            recordings._compute_pbx_group_user_ids()
        channels = self.env['connect.channel'].sudo().search([
            '|',
            ('caller_user', 'in', user_ids.ids),
            ('called_user', 'in', user_ids.ids),
        ])
        if channels:
            channels._compute_pbx_group_user_ids()
