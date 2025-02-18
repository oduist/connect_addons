# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import json
import logging
import requests
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .twiml import pretty_xml
from .settings import debug

logger = logging.getLogger(__name__)


class Queue(models.Model):
    _name = 'connect.queue'
    _description = 'Queue'

    sid = fields.Char('SID', readonly=True)
    name = fields.Char(required=True)
    agents = fields.Many2many('connect.user')
    action_url = fields.Char(compute='_get_urls')
    wait_app = fields.Many2one('connect.twiml', string='Client Wait App', ondelete='restrict')
    wait_url = fields.Char(compute='_get_urls')
    connect_app = fields.Many2one('connect.twiml', string='Agent Connect App', ondelete='restrict')
    disconnect_app = fields.Many2one('connect.twiml', string='Client Disconnect App', ondelete='restrict')
    record_calls = fields.Boolean()
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number')

    def _get_urls(self):
        api_url = self.env['connect.settings'].get_param('api_url')
        for rec in self:
            rec.action_url = urljoin(api_url, 'twilio/webhook/queue/{}/on_action'.format(rec.id))
            rec.wait_url = urljoin(api_url, 'twilio/webhook/queue/{}/render_wait_app'.format(rec.id))

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'queue')

    @api.model
    def on_action(self, q_id, request):
        q = self.sudo().browse(q_id)
        debug(self, 'On queue action: %s' % json.dumps(request, indent=2))
        # Update sid
        q.write({
            'sid': request['QueueSid'],
        })
        if q.disconnect_app:
            return q.disconnect_app.render(request)
        else:
            return pretty_xml('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>')

    @api.model
    def render_wait_app(self, q_id, request):
        debug(self, 'Render Wait App: {}'.format(json.dumps(request, indent=2)))
        q = self.sudo().browse(q_id)
        # Call agents
        client = self.env['connect.settings'].get_client()
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus')
        user = self.env['connect.user'].get_user_by_uri(request.get('From'))
        if user:
            callerId = user.exten.number or user.callerid_number.phone_number
            if not callerId:
                # Get default number callerid.
                default_number = self.env['connect.number'].search([('is_default', '=', True)], limit=1)
                callerId = default_number.phone_number
        else:
            callerId = request.get('From')
        if q.connect_app:
            queue_args = '<Queue url="{}">{}</Queue>'.format(q.connect_app.voice_url, q.name)
        else:
            queue_args = '<Queue>{}</Queue>'.format(q.name)
        record_args = 'record="record-from-answer" recordingStatusCallback="{}"'.format(
            record_status_url) if q.record_calls else ''
        for agent in q.agents:
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
                <Response>
                    <Say>Incoming queue call</Say>
                    <Dial timeout="60" {}>{}</Dial>
                    <Redirect/>
                </Response>
            """.format(record_args, queue_args)
            enabled_channels = []
            if agent.sip_enabled:
                enabled_channels.append('sip')
            if agent.client_enabled:
                enabled_channels.append('client')
            for channel in enabled_channels:
                to = '{}:{}'.format(channel, agent.uri)
                get_param = self.env['connect.settings'].sudo().get_param
                api_url = get_param('api_url')
                status_url = urljoin(api_url, 'twilio/webhook/callstatus')
                call = client.calls.create(
                    twiml=twiml,
                    to=to,
                    from_=callerId,
                    status_callback=status_url,
                    status_callback_event=['initiated','answered', 'completed'],
                    status_callback_method='POST')
                # Create the call for the channel update
                self.env['connect.channel'].create({
                    'sid': call.sid,
                    'parent_sid': request['CallSid']
                })
        # Render wait app
        if q.wait_app:
            return q.wait_app.render(request)
        else:
            return requests.get('https://twimlets.com/holdmusic?Bucket=com.twilio.music.classical&'
                'Message=thankyou%20for%20waiting.%20please%20stay%20on%20the%20line').text

    def render(self, request={}, params={}):
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Enqueue action="{}" waitUrl="{}">{}</Enqueue><Hangup/></Response>'.format(
            self.action_url, self.wait_url, self.name)
        debug(self, 'Queue render: {}'.format(pretty_xml(twiml)))
        self.ensure_one()
        return pretty_xml(twiml)
