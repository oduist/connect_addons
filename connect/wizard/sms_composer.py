# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

from odoo import models


class SendSMS(models.TransientModel):
    _inherit = 'sms.composer'

    def _action_send_sms(self):
        number = re.sub(r"[^\d+]+", "", self.recipient_single_number)
        self.env['connect.message'].send(number, self.body, self.res_id, self.res_model)
        return super()._action_send_sms()
