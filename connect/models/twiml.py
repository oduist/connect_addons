# -*- coding: utf-8 -*-

import datetime
import jinja2
import logging
import random
import time
from urllib.parse import urljoin
from xml.dom.minidom import parseString
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import debug

logger = logging.getLogger(__name__)

# Make XML pretty.
def pretty_xml(content):
    dom = parseString(content)
    pretty_content = dom.toprettyxml()
    # Filter out empty lines
    return "\n".join([line for line in pretty_content.splitlines() if line.strip()])


class TwiML(models.Model):
    _name = 'connect.twiml'
    _description = 'TwiML app'
    _order = 'name'

    sid = fields.Char('SID', readonly=True)
    name = fields.Char(required=True)
    description = fields.Text()
    code_type = fields.Selection([
        ('twiml', 'TwiML'),
        ('twipy', 'TwiPy'),
        ('model_method', 'model.method')
        ], help='Type of the language. To call mymodel.render() set mymodel.render as model.method',
        required=True, default='twiml')
    twiml = fields.Text(required=True, string='TwiML',
        default=pretty_xml('<?xml version="1.0" encoding="UTF-8"?><Response><Say>Hello</Say></Response>'))
    twipy = fields.Text('TwiPy')
    model = fields.Char()
    method = fields.Char()
    voice_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    voice_fallback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    voice_status_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number')


    def create_twilio_app(self, client):
        self.ensure_one()
        application = client.applications.create(
            voice_url=self.voice_url,
            voice_fallback_url=self.voice_fallback_url,
            friendly_name=self.name,
            status_callback=self.voice_status_url,
        )
        self.sid = application.sid
        debug(self, 'Created TwiML app {} in Twilio.'.format(self.name))
        return application

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('install_mode') == True:
            # We do not create TwiML on installation as we don't have API keys yet.
            return super().create(vals_list)
        client = self.env['connect.settings'].get_client()
        records = super().create(vals_list)
        for rec in records:
            rec.create_twilio_app(client)
        return records

    def write(self, vals):
        res = super().write(vals)
        client = self.env['connect.settings'].get_client()
        for rec in self:
            if rec.sid:
                rec.update_twilio_app(client)

    def update_twilio_app(self, client):
        self.ensure_one()
        try:
            application = client.applications(self.sid).update(
                voice_url=self.voice_url,
                voice_fallback_url=self.voice_fallback_url,
                friendly_name=self.name,
                status_callback=self.voice_status_url,
            )
            debug(self, 'TwiML app {} updated.'.format(self.name))
            return application
        except Exception as e:
            if 'not found' in str(e):
                return self.create_twilio_app(client)
            else:
                raise

    def unlink(self):
        client = self.env['connect.settings'].get_client()
        for rec in self:
            if rec.sid:
                try:
                    client.applications(rec.sid).delete()
                except Exception as e:
                    if 'not found' in str(e):
                        logger.warning('Cannot delete app %s in Twilio, not found', rec.name)
                    else:
                        raise
        return super().unlink()

    @api.model
    def sync(self):
        client = self.env['connect.settings'].get_client()
        for rec in self.search([]):
            rec.update_twilio_app(client)

    def _get_twilio_urls(self):
        api_url = self.env['connect.settings'].get_param('api_url')
        fallback_url = self.env['connect.settings'].get_param('api_fallback_url')
        for rec in self:
            rec.voice_status_url = urljoin(api_url, 'twilio/webhook/callstatus')
            rec.voice_url = urljoin(api_url, 'twilio/webhook/twiml/{}'.format(rec.id))
            if fallback_url:
                rec.voice_fallback_url = urljoin(fallback_url, 'twilio/webhook/twiml')
            else:
                rec.voice_fallback_url = ''

    @api.constrains('twipy')
    def _check_syntax(self):
        if self.code_type == 'python' and self.twipy:
            self.render()

    def render(self, request={}, params={}):
        # Render under admin privs. Also do not check Twilio Signature here!
        self = self.sudo()
        self.ensure_one()
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        recording_voice_status_url = urljoin(api_url, 'app/connect/webhook/recordingstatus')
        call_voice_status_url = urljoin(api_url, 'app/connect/webhook/callstatus')
        params.update({
            'recording_voice_status_url': recording_voice_status_url,
            'call_voice_status_url': call_voice_status_url,
        })
        # Return twiml as is if it's not python
        if self.code_type == 'twiml':
            res = self.render_twiml(request=request, params=params)
        elif self.code_type == 'twipy':
            res = self.render_python(request=request, params=params)
        elif self.code_type == 'model_method':
            res = str(getattr(self.env[self.model], self.method)(request=request, params=params))
        debug(self, 'TwiML render result: %s' % pretty_xml(res))
        return res

    def render_twiml(self, request={}, params={}):
        environment = jinja2.Environment()
        template = environment.from_string(self.twiml)
        # Join request and params value and render the final TwiML.
        request.update(params)
        res = template.render(**request)
        return res

    def render_python(self, request={}, params={}):
        import twilio
        # Render
        try:
            exec(self.twipy, {}, {
                'logger': logger,
                'request': request,
                'params': params,
                'twilio': twilio,
                'user': self.env.user,
                'context': self.env.context,
                'env': self.env,
                'rec': self,
                'self': self,
                'pretty_xml': pretty_xml,
                'random': random,
                'datetime': datetime,
                'time': time,
            })
            # We expect that twipy final line is to assign the result to twiml field.
            return self.twiml
        except Exception as e:
            logger.exception('TwiML render error:')
            raise ValidationError(str(e))

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'twiml')

    @api.onchange('code_type')
    def _set_default_twipy_code(self):
        if self.code_type == 'twipy' and not self.twipy:
            self.twipy = """from twilio.twiml.voice_response import VoiceResponse, Dial, Gather, Say, Hangup

# datetime: Python datetime library.
# logger: logger - logger.info('test')
# random: Python random library.
# request: request - dict, call data from the Twilio request.
# params: params - dict, additional params set by the request handler.
# time: Python time library.
# twilio: twilio - Twilio python library.
# self: curreny TwiPy recordset.

response = VoiceResponse()
user_name = self.env.user.name
response.say('Welcome {} to the world of Connect!'.format(user_name))
self.twiml = response
"""
