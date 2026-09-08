# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re

from odoo import api, models, fields, release
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class SendSMS(models.TransientModel):
    _inherit = 'sms.composer'

    outgoing_callerid = fields.Selection(selection='_list_all_numbers')

    @api.model
    def _list_all_numbers(self):
        self._cr.execute("SELECT phone_number, COALESCE(phone_number, phone_number) FROM connect_number ORDER BY 2")
        return self._cr.fetchall()

    def _connect_format_number(self, number):
        if not number:
            return False
        if release.version_info[0] < 17:
            return re.sub(r"[^\d+]+", "", number)
        return self._phone_format(number=number)

    def _action_send_sms(self):
        """Send through Twilio instead of creating sms.sms records.

        Follows core's own split: recipient_single_number is only computed for
        a single document, so every batch composition -- server actions, list
        view, any multi-record selection -- has to resolve its own number and
        body per record.
        """
        records = self._get_records()
        if (self.composition_mode != 'numbers' and records
                and not self.comment_single_recipient
                and isinstance(records, self.pool['mail.thread'])):
            return self._connect_send_records(records)
        return self._connect_send_numbers()

    def _connect_send_numbers(self):
        """One body sent to the composer's own numbers."""
        if self.sanitized_numbers:
            numbers = self.sanitized_numbers.split(',')
        else:
            numbers = [self.recipient_single_number_itf or self.recipient_single_number]
        numbers = [n for n in map(self._connect_format_number, numbers) if n]
        if not numbers:
            raise ValidationError(
                'No valid phone number to send this message to. Add one on the '
                'recipient and send again.')
        for number in numbers:
            self.env['connect.message'].send(
                number, self.body, self.res_id, self.res_model, self.outgoing_callerid)

    def _connect_send_records(self, records):
        """One message per record, each on its own number and rendered body."""
        recipients = records._sms_get_recipients_info(force_field=self.number_field_name)
        unreachable = records.filtered(lambda rec: not recipients[rec.id]['sanitized'])
        if unreachable:
            raise ValidationError(
                'No valid phone number for: %s' % ', '.join(
                    '%s (%s)' % (rec.display_name, recipients[rec.id]['number'] or 'none')
                    for rec in unreachable))
        # Numbers on the phone blacklist have opted out; core cancels them in
        # batch mode, and a sent message cannot be taken back.
        blacklisted = set(self._get_blacklist_record_ids(records, recipients))
        bodies = self._prepare_body_values(records)
        for record in records:
            if record.id in blacklisted:
                logger.info('Not messaging blacklisted number of %s %s.',
                            records._name, record.id)
                continue
            self.env['connect.message'].send(
                recipients[record.id]['sanitized'], bodies[record.id],
                record.id, records._name, self.outgoing_callerid)
