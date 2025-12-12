# -*- coding: utf-8 -*-

import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
import phonenumbers
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from odoo.addons.connect.models.settings import format_connect_response, debug
from odoo.addons.connect.models.twiml import pretty_xml


logger = logging.getLogger(__name__)


def have_same_country_code(num1: str, num2: str) -> bool:
    try:
        phone1 = phonenumbers.parse(num1, None)
        phone2 = phonenumbers.parse(num2, None)
        return phone1.country_code == phone2.country_code
    except phonenumbers.NumberParseException:
        return False


class Domain(models.Model):
    _inherit = "connect.domain"

    byoc = fields.Many2one('connect.byoc', string='BYOC', readonly=True)

    def get_byoc_caller_id_number(self, byoc, number, callerId):
        if byoc:
            if not callerId and byoc.default_callerid:
                debug(self, "Case 1: user's callerid not set. Use BYOC's callerid.")
                return byoc.default_callerid.number
            elif not callerId and not byoc.default_callerid:
                debug(self, "Case 2: user's callerid not set. Use system default.")
                default_number = self.env["connect.outgoing_callerid"].search(
                    [("is_default", "=", True)], limit=1
                )
                return default_number.number
            elif callerId and not byoc.default_callerid:
                debug(self, "Case 3: Using user's callerID.")
                return callerId
            elif callerId and byoc.default_callerid:
                if have_same_country_code(number, callerId):
                    debug(self, "Case 4: Same country, using user's caller ID.")
                    return callerId
                else:
                    debug(self, "Case 5: Different country, using BYOC's caller ID.")
                    return byoc.default_callerid.number
        else:
            # No BYOC for route, use user's callerid or default.
            if callerId:
                return callerId
            else:
                return self.env["connect.outgoing_callerid"].search(
                    [("is_default", "=", True)], limit=1).number


    def originate_external_call(self, number, request, params={}):
        debug(self, "Outgoing call to %s" % number)
        # Find outgoing rules.
        rule = self.env["connect.outgoing_rule"].find_rule(number)
        if not rule:
            return "<Response><Say>No outgoing rule found for this destination! Goodbye!</Say></Response>"
        # Find the user by caller.
        user = self.env["connect.user"].get_user_by_uri(request.get("Caller"))
        callerId = self.get_byoc_caller_id_number(rule.byoc, number, user.outgoing_callerid.number)
        if not callerId:
            return "<Response><Say>You must select a default number for caller ID!</Say></Response>"
        response = VoiceResponse()
        api_url = self.env["connect.settings"].get_param("api_url")
        status_url = urljoin(api_url, "twilio/webhook/callstatus")
        record_status_url = urljoin(api_url, "twilio/webhook/recordingstatus")
        call_duration_limit = int(self.env['connect.settings'].sudo().get_param('call_duration_limit'))
        if user.record_calls:
            dial = Dial(
                timeout=60,
                callerId=callerId,
                timeLimit=call_duration_limit,
                record="record-from-answer",
                recordingStatusCallback=record_status_url,
            )
        else:
            dial = Dial(timeout=60, callerId=callerId, timeLimit=call_duration_limit)
        if rule.byoc:
            # Apply number manipulation
            if rule.trim_leading_digits and rule.trim_leading_digits > 0:
                number = number[rule.trim_leading_digits:]
                debug(self, "Trimmed first %d digits, new number: %s" % (rule.trim_leading_digits, number))
            if rule.add_prefix:
                number = rule.add_prefix + number
                debug(self, "Added prefix '%s', new number: %s" % (rule.add_prefix, number))
            
            dial.number(
                number,
                byoc=rule.byoc.sid,
                statusCallback=status_url,
                statusCallbackEvent="initiated answered completed",
            )
        else:
            dial.number(
                number,
                statusCallback=status_url,
                statusCallbackEvent="initiated answered completed",
            )
        response.append(dial)
        debug(self, "Originate external BYOC: %s" % pretty_xml(str(response)))
        return response
