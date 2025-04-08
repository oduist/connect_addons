# -*- coding: utf-8 -*-
import logging
import random
import uuid
from odoo import models, fields, api, tools, release

logger = logging.getLogger(__name__)

PIN_CODE_RANGE = [100000, 999999]


class ResUser(models.Model):
    _inherit = 'res.users'

    connect_user = fields.Many2one('connect.user', compute='_get_connect_user')
    # PIN code to access the system by phone.
    pin_code = fields.Char(string='PIN code')

    _sql_constraints = [
        ('user_pin_code_unique', 'UNIQUE(pin_code)', 'This PIN code is already used!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        new_numbers = []
        for vals in vals_list:
            vals['pin_code'] = uuid.uuid4().hex
            def get_new_number():
                while True:
                    new_number = random.randint(*PIN_CODE_RANGE)
                    if not self.search([('pin_code', '=', new_number)]) and new_number not in new_numbers:
                        new_numbers.append(new_number)
                        return new_number
            vals['pin_code'] = get_new_number()
        users = super().create(vals_list)
        return users

    def _get_connect_user(self):
        for rec in self:
            rec.connect_user = self.env['connect.user'].search([('user', '=', rec.id)])

    @api.model
    def connect_notify(self, message, title='PBX', notify_uid=None,
                             sticky=False, warning=False):
        """Send a notification to logged in Odoo user.

        Args:
            message (str): Notification message.
            title (str): Notification title. If not specified: PBX.
            uid (int): Odoo user UID to send notification to. If not specified: calling user UID.
            sticky (boolean): Make a notiication message sticky (shown until closed). Default: False.
            warning (boolean): Make a warning notification type. Default: False.
        Returns:
            Always True.
        """
        # Use calling user UID if not specified.
        if not notify_uid:
            notify_uid = self.env.uid

        if release.version_info[0] < 15:
            self.env['bus.bus'].sendone(
                'connect_actions_{}'.format(notify_uid),
                {
                    'action': 'notify',
                    'message': message,
                    'title': title,
                    'sticky': sticky,
                    'warning': warning
                })
        else:
            self.env['bus.bus']._sendone(
                'connect_actions_{}'.format(notify_uid),
                'connect_notify',
                {
                    'message': message,
                    'title': title,
                    'sticky': sticky,
                    'warning': warning
                })

        return True
