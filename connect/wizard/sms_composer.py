# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models, fields


class SendSMS(models.TransientModel):
    _inherit = 'sms.composer'

    outgoing_callerid = fields.Selection(selection='_list_all_numbers')

    @api.model
    def _list_all_numbers(self):
        self._cr.execute("SELECT phone_number, COALESCE(phone_number, phone_number) FROM connect_number ORDER BY 2")
        return self._cr.fetchall()

    def _action_send_sms(self):
        number = self.recipient_single_number or self.recipient_single_number_itf
        number = self._phone_format(number=number)
        self.env['connect.message'].send(number, self.body, self.res_id, self.res_model, self.outgoing_callerid)
        return super()._action_send_sms()
