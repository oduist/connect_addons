# -*- coding: utf-8 -*-

import inspect
import json
import logging
import requests
import random
import re
import string
from urllib.parse import urljoin
import uuid
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError, UserError
from twilio.rest import Client
from twilio.request_validator import RequestValidator


logger = logging.getLogger(__name__)

TWILIO_LOG_LEVEL = logging.WARNING

############### SETTINGS #####################################
MODULE_NAME = 'connect'
API_URL = 'https://eu-central-1.api.oduist.com'

MAX_EXTEN_LEN = 4

PROTECTED_FIELDS = ['display_auth_token', 'display_twilio_api_secret', 'display_openai_api_key']


def debug(rec, message, level='info'):
    caller_module = inspect.stack()[1][3]
    if level == 'info':
        fun = logger.info
    elif level == 'warning':
        fun = logger.warning
        fun('++++++ {}: {}'.format(caller_module, message))
    elif level == 'error':
        fun = logger.error
        fun('++++++ {}: {}'.format(caller_module, message))
    if rec.env['connect.settings'].sudo().get_param('debug_mode'):
        rec.env['connect.debug'].sudo().create({
            'model': str(rec),
            'message': caller_module + ': ' + message,
        })
        if level == 'info':
            fun('++++++ {}: {}'.format(caller_module, message))


def format_connect_response(text):
    if not isinstance(text, str):
        text = str(text)
    symbol_pattern = re.compile(r'(\x08.)|\x08')
    text = symbol_pattern.sub('', text)
    color_pattern = re.compile(r'\x1b\[[\d;]+m')
    text = color_pattern.sub('', text)
    return text


def generate_password():
    characters = [
        random.choice(string.ascii_lowercase),
        random.choice(string.ascii_uppercase),
        random.choice(string.digits)
    ]
    characters += random.choices(string.ascii_letters + string.digits, k=20)
    random.shuffle(characters)
    return ''.join(characters)

######### COPY FROM SETTINGS TO ELIMINATE CIRULAR IMPORT
def strip_number(number):
    """Strip number formating"""
    if not isinstance(number, str):
        return number
    pattern = r'[\s\(\)\-\+]'
    return re.sub(pattern, '', number).lstrip('0')


class Settings(models.Model):
    """One record model to keep all settings. The record is created on
    get_param / set_param methods on 1-st call.
    """
    _name = 'connect.settings'
    _description = 'Settings'

    name = fields.Char(compute='_get_name')
    debug_mode = fields.Boolean()
    account_sid = fields.Char(string='Account SID')
    auth_token = fields.Char(groups="base.group_erp_manager,connect.group_connect_webhook")
    display_auth_token = fields.Char()
    twilio_api_key = fields.Char()
    twilio_api_secret = fields.Char(groups="base.group_erp_manager")
    display_twilio_api_secret = fields.Char()
    twilio_balance = fields.Char(readonly=True)
    openai_api_key = fields.Char(groups="base.group_erp_manager")
    display_openai_api_key = fields.Char()
    number_search_operation = fields.Selection([('=', 'Equal'), ('like', 'Like')], default='=', required=True)
    ############# RECORDING & TRANSCRIPT FIELDS ##############################################
    proxy_recordings = fields.Boolean(help='Re-stream recordings using Odoo user auth.', default=True)
    transcript_calls = fields.Boolean()
    transcription_rules = fields.One2many('connect.transcription_rule', 'settings')
    summary_prompt = fields.Text(required=True, default='Summarise this phone call')
    register_summary = fields.Boolean(help='Register summary at partner of reference chat.')
    remove_recording_after_transcript = fields.Boolean()
    ############################################################
    instance_uid = fields.Char('Instance UID', compute='_get_instance_data')
    api_key = fields.Char('API Key', compute='_get_instance_data')
    api_url = fields.Char('API URL', compute='_get_instance_data')
    api_fallback_url = fields.Char('API Fallback URL')
    twilio_verify_requests = fields.Boolean(default=True, string='Verify Twilio Requests')
    media_url = fields.Char()
    # Registration fields
    partner_code = fields.Char()
    show_partner_code = fields.Boolean(default=True)
    is_registered = fields.Boolean()
    i_agree_to_register = fields.Boolean()
    i_agree_to_contact = fields.Boolean()
    i_agree_to_receive = fields.Boolean()
    installation_date = fields.Datetime(compute='_get_instance_data')
    module_version = fields.Char(compute='_get_instance_data')
    odoo_version = fields.Char(compute='_get_instance_data')
    admin_name = fields.Char(compute='_get_instance_data')
    admin_phone = fields.Char(compute='_get_instance_data')
    admin_email = fields.Char(compute='_get_instance_data')
    company_name = fields.Char(compute='_get_instance_data')
    company_email = fields.Char(compute='_get_instance_data')
    company_phone = fields.Char(compute='_get_instance_data')
    company_country = fields.Char(compute='_get_instance_data')
    company_state_name = fields.Char(compute='_get_instance_data')
    company_country_code = fields.Char(compute='_get_instance_data')
    company_country_name = fields.Char(compute='_get_instance_data')
    company_city = fields.Char(compute='_get_instance_data')
    web_base_url = fields.Char(compute='_get_instance_data', string='Odoo URL')

    def _get_instance_data(self):
        module = self.env['ir.module.module'].sudo().search([('name', '=', MODULE_NAME)])
        for rec in self:
            rec.module_version = module.installed_version[-3:]
            version = self.env['ir.module.module'].search([('name', '=', 'base')], limit=1).latest_version
            major_version = version.split('.')[0] + '.' + version.split('.')[1]
            rec.odoo_version = major_version
            rec.instance_uid = self.env['ir.config_parameter'].sudo().get_param('connect.instance_uid')
            # Format API URL according to the preferred region or dev URL.
            rec.installation_date = self.env['ir.config_parameter'].sudo().get_param('connect.installation_date')
            rec.api_url = self.env['ir.config_parameter'].sudo().get_param('connect.api_url')
            rec.api_key = self.env['ir.config_parameter'].sudo().get_param('connect.api_key')
            rec.company_email = self.env.user.company_id.email
            rec.company_name = self.env.user.company_id.name
            rec.company_phone = self.env.user.company_id.phone
            rec.company_country = self.env.user.company_id.country_id.name
            rec.company_city = self.env.user.company_id.city
            rec.company_country_code = self.env.user.company_id.country_id.code
            rec.company_country_name = self.env.user.company_id.country_id.name
            rec.company_state_name = self.env.user.company_id.partner_id.state_id.name
            rec.admin_name = self.env.user.partner_id.name
            rec.admin_email = self.env.user.partner_id.email
            rec.admin_phone = self.env.user.partner_id.phone
            rec.web_base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

####################################################################################
##### REGISTRATION ##### NO CHANGES ALLOWED HERE ###########################

    @api.model
    def connect_notify(self, message, title='Connect', notify_uid=None,
                             sticky=False, warning=False):
        """Send a notification to logged in Odoo user.

        Args:
            message (str): Notification message.
            title (str): Notification title. If not specified: PBX.
            uid (int): Odoo user UID to send notification to. If not specified: caller user UID.
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

    @api.model
    def connect_reload_view(self, model):
        if release.version_info[0] < 15:
            msg = {
                'action': 'reload_view',
                'model': model,
            }
            self.env['bus.bus'].sendone('connect_actions', json.dumps(msg))
        else:
            msg = {'model': model}
            self.env['bus.bus']._sendone(
                'connect_actions',
                'reload_view',
                msg
            )


####################################################################################
    @api.model
    def set_defaults(self):
        # Called on installation to set default value
        api_url = self.get_param('api_url')
        if not api_url:
            # Set default value
            web_base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            self.env['ir.config_parameter'].set_param('connect.api_url', web_base_url)
        installation_date = self.env['ir.config_parameter'].sudo().get_param('connect.installation_date')
        if not installation_date:
            installation_date = fields.Datetime.now()
            self.env['ir.config_parameter'].set_param('connect.installation_date', installation_date)

    @api.model
    def _get_name(self):
        for rec in self:
            rec.name = 'General Settings'

    def open_settings_form(self):
        rec = self.search([])
        if not rec:
            rec = self.sudo().with_context(no_constrains=True).create({})
        else:
            rec = rec[0]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'connect.settings',
            'res_id': rec.id,
            'name': 'General Settings',
            'view_mode': 'form',
            'view_type': 'form',
            'view_id': self.env.ref('connect.connect_settings_form').id,
            'target': 'current',
        }

    @api.model
    # @ormcache('param')
    def get_param(self, param, default=False):
        """
        """
        data = self.search([])
        if not data:
            data = self.sudo().with_context(no_constrains=True).create({})
        else:
            data = data[0]
        return getattr(data, param, default)

    @api.model
    def set_param(self, param, value):
        data = self.search([])
        if not data:
            data = self.sudo().with_context(no_constrains=True).create({})
        else:
            data = data[0]
        setattr(data, param, value)

    @api.model
    def set_instance_uid(self, instance_uid=False):
        existing_uid = self.env['ir.config_parameter'].get_param('connect.instance_uid')
        if not existing_uid:
            if not instance_uid:
                instance_uid = str(uuid.uuid4())
            self.env['ir.config_parameter'].set_param('connect.instance_uid', instance_uid)

    def register_instance(self):
        if not self.env.user.has_group('base.group_system'):
            raise ValidationError('Only Odoo admin can do it!')
        if self.get_param('is_registered'):
            raise ValidationError('This instance is already registered!')
        admin_email = self.get_param('admin_email')
        admin_phone = self.get_param('admin_phone')
        company_email = self.get_param('company_email')
        if not company_email or not admin_email or not admin_phone:
            raise ValidationError('Please enter all required fields: company email, '
                                  'your email, and your phone!')
        if admin_email == 'admin@example.com' or company_email == 'admin@example.com':
            raise ValidationError('Please set your real email address, not admin@example.com.')
        data = {
            'company_name': self.get_param('company_name'),
            'company_country': self.get_param('company_country'),
            'company_state_name': self.get_param('company_state_name'),
            'company_country_code': self.get_param('company_country_code'),
            'company_country_name': self.get_param('company_country_name'),
            'company_email': company_email,
            'company_city': self.get_param('company_city'),
            'company_phone': self.get_param('company_phone'),
            'admin_name': self.get_param('admin_name'),
            'admin_email': admin_email,
            'admin_phone': admin_phone,
            'module_version': self.get_param('module_version'),
            'module_name': MODULE_NAME,
            'odoo_version': self.get_param('odoo_version'),
            'odoo_url': self.get_param('web_base_url'),
            'installation_date': self.get_param('installation_date').strftime("%Y-%m-%d"),
            'partner_code': self.get_param('partner_code'),
        }
        res = self.make_api_request(API_URL, requests.post, data=data)
        if not res and self.get_param('api_fallback_url'):
            # Make a request and give error if fallback API endpoint is not available.
            logger.warning('Making a request to API fallback.')
            res = self.make_api_request(
                self.get_param('api_fallback_url'), requests.post, data=data, raise_on_error=True)
        # The register function must return json data with api_key.
        res = res.json()
        self.env['ir.config_parameter'].sudo().set_param('connect.api_key', res['api_key'])
        self.set_param('is_registered', True)

    def unregister_instance(self):
        if not self.env.user.has_group('base.group_system'):
            raise ValidationError('Only Odoo admin can do it!')
        if not self.get_param('api_key'):
            raise ValidationError('This instance is not registered!')
        instance_uid = self.get_param('instance_uid') or ''
        api_key = self.get_param('api_key') or ''
        res = self.make_api_request(
            urljoin(API_URL, 'registration'),  requests.delete, headers={'x-api-key': api_key})
        if not res and self.get_param('api_fallback_url'):
            logger.warning('Making a request to API fallback.')
            res = self.make_api_request(
                urljoin(self.get_param('api_fallback_url'), 'registration'), requests.delete,
                headers={'x-api-key': api_key}, raise_on_error=True)
        self.env['ir.config_parameter'].set_param('connect.api_key', '')
        self.set_param('is_registered', False)

    def update_company_data_button(self):
        main_company = self.env.company
        if not main_company:
            raise UserError("No main company found.")
        return {
            'type': 'ir.actions.act_window',
            'name': main_company.name,
            'res_model': 'res.company',
            'view_mode': 'form',
            'res_id': main_company.id,
            'target': 'new',
        }

    def update_admin_data_button(self):
        return {
            'type': 'ir.actions.act_window',
            'name': self.env.user.partner_id.name,
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.env.user.partner_id.id,
            'target': 'new',
        }

    def make_api_request(self, url, method, data={}, headers={}, raise_on_error=False):
        headers.update({'x-instance-uid': self.get_param('instance_uid')})
        res = None
        try:
            res = method(
                urljoin(url, 'registration'), json=data, headers=headers)
            if res.status_code == 200:
                return res
            if res.status_code == 412:
                raise ValidationError(res.text)
            elif raise_on_error:
                # API gateway error
                raise ValidationError(res.text)
        except Exception as e:
            if raise_on_error:
                raise ValidationError(str(e))

    @api.model_create_multi
    def create(self, vals_list):
        if release.version_info[0] >= 17:
            self.env.registry.clear_cache()
        else:
            self.clear_caches()
        return super(Settings, self).create(vals_list)

    def write(self, vals):
        if self.env.context.get('skip_protected_fields'):
            return super(Settings, self).write(vals)
        res = super(Settings, self).write(vals)
        changed_fields = {}
        for field_name in PROTECTED_FIELDS:
            if vals.get(field_name):
                changed_fields.update({
                    field_name.replace('display_', ''): vals.get(field_name),
                    field_name: '*' * len(vals.get(field_name))
                })
        if changed_fields:
            # Set keys user super access.
            self.with_context(skip_protected_fields=True).sudo().write(changed_fields)
        # Reset cache
        if release.version_info[0] >= 17:
            self.env.registry.clear_cache()
        else:
            self.clear_caches()



    @api.model
    def pbx_reload_view(self, model):
        if release.version_info[0] < 15:
            msg = {
                'action': 'reload_view',
                'model': model,
            }
            self.env['bus.bus'].sendone('connect_actions', json.dumps(msg))
        else:
            msg = {'model': model}
            self.env['bus.bus']._sendone(
                'connect_actions',
                'reload_view',
                json.dumps(msg)
            )

    @api.model
    def get_client(self):
        try:
            self.check_access_rule('read') if release.version_info[0] < 18 else self.check_access('read')
            account_sid = self.sudo().get_param('account_sid')
            auth_token = self.sudo().get_param('auth_token')
            client = Client(account_sid, auth_token)
            client.http_client.logger.setLevel(TWILIO_LOG_LEVEL)
            return client
        except Exception as e:
            if 'Credentials are required to create a TwilioClient' in str(e):
                raise ValidationError('Set Twilio API keys first!')
            else:
                raise

    @api.model
    def check_twilio_request(self, request):
        if not self.sudo().get_param('twilio_verify_requests'):
            return True
        if not request.get('X-TWILIO-SIGNATURE'):
            logger.error('Request does not contain X-TWILIO-SIGNATURE! Ignoring.')
            return False
        validator = RequestValidator(self.sudo().get_param('auth_token'))
        url = request.pop('X-TWILIO-WEBHOOK-URL', '')
        signature = request.pop('X-TWILIO-SIGNATURE', '')
        request_valid = validator.validate(url, request, signature)
        if not request_valid:
            logger.error('Twilio request is not valid: %s', json.dumps(request, indent=2))
        return request_valid

    def sync(self):
        if not (self.sudo().get_param('account_sid') and self.sudo().get_param('auth_token')):
            raise ValidationError('You must set account SID and Auth token!')
        self.env['connect.twiml'].sync()
        self.env['connect.domain'].sync()
        self.env['connect.number'].sync()
        self.env['connect.outgoing_callerid'].sync()
        self.env['connect.byoc'].sync()
        self.connect_notify('Sync complete.')

    # Called from the settings.
    def reformat_numbers_button(self):
        for rec in self.env['res.partner'].search([]):
            rec.phone = rec._normalize_phone(rec.phone)
            rec.mobile = rec._normalize_phone(rec.mobile)

    @api.model
    def originate_call(self, number, res_model=None, res_id=None, user=None):
        number = strip_number(number)
        if len(number) > MAX_EXTEN_LEN:
            number = '+{}'.format(number)
        client = self.get_client()
        partner_id = False
        obj = self.env[res_model].browse(res_id)
        if res_model == 'res.partner':
            partner_id = res_id
        elif hasattr(obj, 'partner_id'):
            partner_id = obj.partner_id.id
        elif hasattr(obj, 'partner'):
            partner_id = obj.partner.id
        # If user is not set use current user.
        if not user:
            user = self.env.user
        if not user.connect_user:
            raise ValidationError('User does not have a SIP username defined!')
        ring_options = {}
        if user.connect_user.sip_enabled:
            ring_options['sip'] = 'sip:{}'.format(self.env.user.connect_user.uri)
        if user.connect_user.client_enabled:
            ring_options['client'] = 'client:{}?autoAnswer=yes&Partner={}'.format(self.env.user.connect_user.uri, partner_id)
        to = ring_options.get(self.env.user.connect_user.ring_first)
        if not to:
            # Get available option.
            to = list(ring_options.items())[0][1]
        to += '&From={}'.format(number)
        exten = self.env['connect.exten'].search([('number', '=', number)], limit=1)
        default_number = self.env['connect.outgoing_callerid'].search([('is_default', '=', True)], limit=1)
        if exten:
            # Set callerID to user's extension.
            callerId = user.connect_user.exten.number
        elif user.connect_user.outgoing_callerid:
            callerId = user.connect_user.outgoing_callerid.number
        else:
            callerId = default_number.number
        api_url = self.sudo().get_param('api_url')
        instance_uid = self.sudo().get_param('instance_uid', '')
        status_url = urljoin(api_url, 'twilio/webhook/callstatus')
        if exten:
            # Internal call to an extension.
            twiml = exten.render()
        else:
            # External call to PSTN. Find outgoing rule.
            rule = self.env['connect.outgoing_rule'].find_rule(number)
            if not rule:
                raise ValidationError('No outgoing rule found for this destination!')
            twiml = """
            <Response>
                <Dial callerId="{}"><Number {} statusCallback='{}' statusCallbackEvent='initiated answered completed'>{}</Number></Dial>
            </Response>
            """.format(
                callerId,
                'byoc="{}"'.format(rule.byoc.sid) if rule.byoc else '',
                status_url, number)
        record = self.env.user.connect_user.record_calls
        channel = client.calls.create(twiml=twiml, to=to, from_=callerId,
            status_callback=status_url,
            record=record, recording_channels='dual',
            status_callback_event=['initiated','answered', 'completed'],
        )
        self.env['connect.channel'].sudo().create({
            'sid': channel.sid,
            'technical_direction': 'outboubd-api',
            'caller_user': user.id,
            'caller_pbx_user': user.connect_user.id,
            'partner': partner_id,
            'called': number,
            'caller': callerId,
        })

    @api.onchange('transcript_calls')
    def _require_openai_key(self):
        if not self.sudo().get_param('openai_api_key'):
            raise ValidationError('You must set OpenAI key first!')