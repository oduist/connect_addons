# -*- coding: utf-8 -*-

import json
import logging
import re
from odoo import fields, models, api, release
from .settings import debug

logger = logging.getLogger(__name__)


class Channel(models.Model):
    _name = 'connect.channel'
    _description = 'Channel'
    _inherit = 'mail.thread'
    _rec_name = 'id'
    _order = 'id desc'

    call = fields.Many2one('connect.call', ondelete='cascade')
    sid = fields.Char('SID', readonly=True)
    parent_channel = fields.Many2one('connect.channel', ondelete='cascade', tracking=True)
    parent_sid = fields.Char('Parent SID', tracking=True, readonly=True)
    partner = fields.Many2one('res.partner', ondelete='set null', tracking=True)
    called = fields.Char(tracking=True)
    to = fields.Char(tracking=True)
    technical_direction = fields.Char(tracking=True, string='Direction')
    status = fields.Char(tracking=True)
    duration = fields.Integer(string='Seconds', tracking=True)
    duration_minutes = fields.Float(string='Minutes', tracking=True)
    duration_billing = fields.Integer(string='Bill Minutes', tracking=True)
    duration_human = fields.Char(compute='_get_duration_human', string='Duration', store=True, tracking=True)
    caller = fields.Char(tracking=True)
    call_type = fields.Selection([
        ('phone', 'Phone'),
        ('whatsapp', 'WhatsApp')
    ], default='phone', index=True, tracking=True)
    # PBX users are Connect SIP or Client users.
    caller_pbx_user = fields.Many2one('connect.user', ondelete='set null', string='Caller PBX User', tracking=True)
    called_pbx_user = fields.Many2one('connect.user', ondelete='set null', string='Called PBX User', tracking=True)
    # Users are Odoo accounts.
    caller_user = fields.Many2one('res.users', string='Caller User', tracking=True)
    called_user = fields.Many2one('res.users', string='Called User', tracking=True)
    # Parsed numbers (domain stripped).
    caller_number = fields.Char(compute='_get_channel_numbers', store=True, index=True)
    called_number = fields.Char(compute='_get_channel_numbers', store=True, index=True)

    @api.depends('caller', 'called')
    def _get_channel_numbers(self):
        re_number_domain = re.compile(r'^(sip|client):(.+)@(.+)$')
        re_client_number = re.compile(r'^client:(\d{8})$')
        re_number = re.compile(r'^(\+?[0-9]+)$')
        re_whatsapp = re.compile(r'^whatsapp:(\+?[0-9]+)$')

        def _get_number(callinfo):
            if not isinstance(callinfo, str):
                return ''
            if re_number.search(callinfo):
                return callinfo
            elif re_whatsapp.search(callinfo):
                # Strip whatsapp: prefix, keep E.164 number
                return re_whatsapp.search(callinfo).group(1)
            elif re_number_domain.search(callinfo):
                user_or_number = re_number_domain.search(callinfo).group(2)
                # Substitute username to his number
                user = self.env['connect.user'].get_user_by_uri(callinfo)
                if user:
                    return user.exten.number
                else:
                    return user_or_number
            elif re_client_number.search(callinfo):
                return re_client_number.search(callinfo).group(1)
            else:
                # We should not be here.
                return ''

        for rec in self:
            rec.caller_number = _get_number(rec.caller)
            rec.called_number = _get_number(rec.called)

    @api.depends('duration')
    def _get_duration_human(self):
        for record in self:
            if record.duration is not None:
                minutes = record.duration // 60
                seconds = record.duration % 60
                record.duration_human = '{:02}:{:02}'.format(minutes, seconds)
                record.duration_minutes = record.duration / 60.0
            else:
                record.duration_minutes = 0
                record.duration_human = "00:00"

    @api.model
    def on_call_status(self, params):
        debug(self, 'On channel status: %s' % json.dumps(params, indent=2))
        # Pre-process for WhatsApp and E.164 normalization
        def strip_whatsapp(v):
            return v.split(':', 1)[1] if isinstance(v, str) and v.startswith('whatsapp:') else v
        caller_raw = params.get('Caller')
        called_raw = params.get('Called')
        to_raw = params.get('To')
        caller_clean = strip_whatsapp(caller_raw)
        called_clean = strip_whatsapp(called_raw)
        to_clean = strip_whatsapp(to_raw)
        call_type = 'whatsapp' if any(isinstance(x, str) and x.startswith('whatsapp:') for x in [caller_raw, called_raw, to_raw]) else 'phone'

        channel = self.search([('sid', '=', params['CallSid'])], limit=1, order='id asc')
        if channel:
            # Update channel data.
            data = {
                'called': called_clean,
                'to': to_clean,
                'technical_direction': params['Direction'],
                'status': params['CallStatus'],
                'duration': int(params.get('CallDuration', 0)),
                'caller': caller_clean,
                'call_type': call_type,
            }
            # Find an existing parent channel.
            if not channel.parent_channel:
                # Check if channel has parent_sid without channel
                if channel.parent_sid:
                    parent_channel = self.search([('sid', '=', channel.parent_sid)])
                    data['parent_channel'] = parent_channel.id
                elif params.get('ParentCallSid'):
                    parent_channel = self.search([('sid', '=', params.get('ParentCallSid'))])
                    data['parent_channel'] = parent_channel.id
                    data['parent_sid'] = parent_channel.parent_channel.sid
            channel.write(data)
            debug(self, 'Channel %s updated.' % channel.id)
        # Channel not found by sid, create it.
        else:
            data = {
                'sid': params['CallSid'],
                'called': called_clean,
                'to': to_clean,
                'technical_direction': params['Direction'],
                'status': params['CallStatus'],
                'duration': int(params.get('CallDuration', 0)),
                'caller': caller_clean,
                'call_type': call_type,
            }
            # Check if channel has parent_sid without channel
            if channel.parent_sid:
                parent_channel = self.search([('sid', '=', channel.parent_sid)])
                data['parent_channel'] = parent_channel.id
            elif params.get('ParentCallSid'):
                parent_channel = self.search([('sid', '=', params.get('ParentCallSid'))])
                data['parent_channel'] = parent_channel.id
                data['parent_sid'] = parent_channel.parent_channel.sid
            # Find caller user
            caller_pbx_user = None
            called_pbx_user = None
            if params.get('Caller'):
                caller_pbx_user = self.env['connect.user'].get_user_by_uri(params['Caller'])
                data['caller_pbx_user'] = caller_pbx_user.id
                data['caller_user'] = caller_pbx_user.user.id
            # Find called user
            if params.get('Called'):
                called_pbx_user = self.env['connect.user'].get_user_by_uri(params['Called'])
                data['called_pbx_user'] = called_pbx_user.id
                data['called_user'] = called_pbx_user.user.id
            # Find the partner (use cleaned numbers)
            if caller_pbx_user and called_clean:
                # User makes outgoing call.
                if (called_clean or '').startswith('+'):
                    data['partner'] = self.env['res.partner'].get_partner_by_number(called_clean).id
                    debug(self, 'Setting partner caller user by called.')
            elif called_pbx_user and caller_clean:
                if (caller_clean or '').startswith('+'):
                    data['partner'] = self.env['res.partner'].get_partner_by_number(caller_clean).id
                    debug(self, 'Setting partner called user by caller.')
            elif params.get('Direction') == 'outbound-dial' and called_clean:
                    data['partner'] = self.env['res.partner'].get_partner_by_number(called_clean).id
                    debug(self, 'Setting partner for outbound dial by called.')
            elif params.get('Direction') == 'inbound' and \
                    (called_clean or '').startswith('+') and (caller_clean or '').startswith('+'):
                debug(self, 'Incoming DID/WhatsApp call. Get the partner from caller number.')
                data['partner'] = self.env['res.partner'].get_partner_by_number(caller_clean).id
            else:
                debug(self, 'Not setting channel partner without channel users.')
            channel = self.with_context(tracking_disable=True).create(data)
            debug(self, 'Channel %s created.' % channel.id)
        return channel

    def transfer(self, to=None):
        self.ensure_one()
        client = self.env['connect.settings'].get_client()
        call = client.calls(self.sid).update(
            twiml="<Response><Say>Ahoy there</Say></Response>")
        print(call.to)

    def connect_notify(self, title='Connect', sticky=False, warning=False):
        """Notify user about incoming call.
        """
        caller = self.caller
        caller_avatar = '/web/static/img/placeholder.png'
        if self.partner:
            caller = """
                <p class="text-center"><strong>Partner:</strong>
                <a href='/web#id={}&model={}&view_type=form'>
                    {}
                </a>
                </p>
            """.format(self.partner.id, 'res.partner', self.partner.name)
            caller_avatar = '/web/image/res.partner/{}/image_1024'.format(self.partner.id)
        elif self.caller_user:
            calling_avatar = '/web/image/res.users/{}/image_1024'.format(self.caller_user.id)

        message = """
        <div class="d-flex align-items-center justify-content-center">
            <div>
                <img style="max-height: 100px; max-width: 100px;"
                        class="rounded-circle"
                        src={}/>
            </div>
            <div>
                <p class="text-center">Incoming call</p>
                {}
            </div>
        </div>
        """.format(caller_avatar, caller)

        if release.version_info[0] < 15:
            self.env['bus.bus'].sendone(
                'connect_actions_{}'.format(self.called_user.id),
                {
                    'action': 'notify',
                    'message': message,
                    'title': title,
                    'sticky': sticky,
                    'warning': warning
                })
        else:
            self.env['bus.bus']._sendone(
                'connect_actions_{}'.format(self.called_user.id),
                'connect_notify',
                {
                    'message': message,
                    'title': title,
                    'sticky': sticky,
                    'warning': warning
                })

        return True
