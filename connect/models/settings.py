# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import inspect
import json
import logging
import requests
import os
import random
import re
import string
from urllib.parse import urljoin
import uuid
from odoo import fields, models, api, release
from odoo.modules.module import get_module_path
from odoo.exceptions import ValidationError
from twilio.rest import Client
from twilio.request_validator import RequestValidator


logger = logging.getLogger(__name__)

TWILIO_LOG_LEVEL = logging.WARNING


############### BILLING SETTINGS #####################################
MODULE_NAME = 'connect'
PRODUCT_CODE = 'prod_RFq8TVNljCDJmH'
BILLING_USER = 'connect.user_connect_billing'
API_URL = 'https://api-{}.connect.com/'
# Starting from Odoo 12.0 there is admin user with ID 2.
ADMIN_USER_ID = 1 if release.version_info[0] <= 11 else 2

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
    eula = fields.Text('EULA', compute='_get_eula')
    is_eula_accepted = fields.Boolean()
    account_sid = fields.Char(string='Account SID')
    auth_token = fields.Char(groups="base.group_erp_manager,connect.group_connect_billing")
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
    #############  BILLING FIELDS   ###############################################
    webhook_region = fields.Selection(
        [('eu-central-1', 'Europe'), ('us-east-1', 'US East')],
        required=True, default='us-east-1')
    webhook_fallback_region = fields.Selection(
        [('eu-central-1', 'Europe'),
         ('us-east-1', 'US East'),
         ('none', 'None'),
        ],
        required=True, default='eu-central-1')
    instance_uid = fields.Char('Instance UID', compute='_get_instance_data')
    api_key = fields.Char('API Key', compute='_get_instance_data')
    api_url = fields.Char('API URL', compute='_get_instance_data')
    api_fallback_url = fields.Char('API Fallback URL', compute='_get_instance_data')
    product_code = fields.Char(compute='_get_instance_data')
    credits = fields.Char(readonly=True)
    is_subscribed = fields.Boolean()
    subscription_pricing = fields.Text('Pricing', readonly=True)
    is_registered = fields.Boolean(compute='_get_instance_data')
    registration_id = fields.Char('Registration Number', compute='_get_instance_data')
    module_name = fields.Char(compute='_get_instance_data')
    module_version = fields.Char(compute='_get_instance_data')
    partner_code = fields.Char()
    discount_code = fields.Char()
    show_partner_code = fields.Boolean(default=True)
    show_discount_code = fields.Boolean(default=True)
    admin_name = fields.Char(required=True, default=lambda x: x.get_registration_defaults('admin_name'))
    admin_phone = fields.Char(default=lambda x: x.get_registration_defaults('admin_phone'))
    admin_email = fields.Char(default=lambda x: x.get_registration_defaults('admin_email'))
    company_name = fields.Char(compute='_get_instance_data')
    company_phone = fields.Char(compute='_get_instance_data')
    company_email = fields.Char(compute='_get_instance_data')
    company_address = fields.Char(compute='_get_instance_data')
    web_base_url = fields.Char('Odoo Access URL',
                               required=True, default=lambda x: x.get_registration_defaults('web_base_url'))
    twilio_verify_requests = fields.Boolean(default=True, string='Verify Twilio Requests')
    media_url = fields.Char()

    def get_registration_defaults(self, field):
        defaults = {
            'admin_name': self.env['res.users'].sudo().browse(ADMIN_USER_ID).partner_id.name,
            'admin_phone': self.env['res.users'].sudo().browse(ADMIN_USER_ID).partner_id.phone or "+1234567890",
            'admin_email': self.env['res.users'].sudo().browse(ADMIN_USER_ID).partner_id.email,
            'web_base_url': self.env['ir.config_parameter'].sudo().get_param('web.base.url'),
        }
        return defaults[field]

    def _get_eula(self):
        for rec in self:
            module_path = get_module_path(MODULE_NAME)
            license_file_path = os.path.join(module_path, 'LICENSE')
            if os.path.exists(license_file_path):
                with open(license_file_path, 'r') as license_file:
                    rec.eula = license_file.read()
            else:
                raise ValidationError("LICENSE file not found!")

    def confirm_eula(self):
        self.set_param('is_eula_accepted', True)

    def _get_instance_data(self):
        module = self.env['ir.module.module'].sudo().search([('name', '=', MODULE_NAME)])
        for rec in self:
            rec.product_code = self.env['ir.config_parameter'].sudo().get_param(
                'connect.{}_product_code'.format(MODULE_NAME)) or PRODUCT_CODE
            rec.module_name = MODULE_NAME
            rec.module_version = module.installed_version[-3:]
            rec.instance_uid = self.env['ir.config_parameter'].sudo().get_param('connect.instance_uid')
            # Adjust API URL to the region
            api_url = self.env['ir.config_parameter'].sudo().get_param('connect.api_url')
            api_region = self.get_param('webhook_region')
            api_fallback_region = self.get_param('webhook_fallback_region')
            # Format API URL according to the preferred region or dev URL.
            rec.api_url = api_url if api_url else API_URL.format(api_region)
            rec.api_fallback_url = API_URL.format(api_fallback_region) if api_fallback_region != 'none' else ''
            rec.api_key = self.env['ir.config_parameter'].sudo().get_param('connect.api_key')
            rec.company_name = self.env.user.company_id.name
            rec.company_email = self.env.user.company_id.email
            rec.company_phone = self.env.user.company_id.phone
            company_address = re.sub(
                r'\n(\s|\n)*', ', ', self.env.user.company_id.partner_id.contact_address).strip().strip(',')
            rec.company_address = company_address
            rec.registration_id = self.env['ir.config_parameter'].sudo().get_param('connect.registration_id')
            rec.is_registered = True if rec.api_key else False

####################################################################################
##### BILLING REGISTRATION ##### NO CHANGES ALLOWED HERE ###########################

    def get_registration_code(self):
        # Send registration code to admin.
        if self.get_param('admin_email') == 'admin@example.com':
            raise ValidationError('Please set your real email address, not admin@example.com.')
        url = urljoin(self.get_param('api_url'), 'signup')
        res = requests.post(url,
            json={
                'email': self.get_param('admin_email'),
                'name': self.get_param('admin_name'),
            },
            headers={'x-instance-uid': self.get_param('instance_uid')}
        )
        if not res.ok:
            raise ValidationError(res.text)
        # Notify works in Odoo starting from 12.0
        if release.version_info[0] >= 12:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Signup",
                    'message': 'Check mail for %s for the registration code!' % self.get_param('admin_email'),
                    'sticky': False,
                    'type': 'info',
                }
            }


    def create_subscription(self):
        # Reset billing user password.
        # This billing account has very limited access (portal) and does not consume Odoo user license.
        # It is used only by our billing system to account resources of this application.
        # Don't change its password manually otherwise your subscription will be interrupted.
        billing_user = self.env.ref(BILLING_USER)
        billing_password = str(uuid.uuid4()) + '1!A'
        billing_user.password = billing_password
        self.env.cr.commit()
        admin_email = self.get_param('admin_email')
        admin_phone = self.get_param('admin_phone')
        if not admin_email or not admin_phone:
            raise ValidationError('Please enter all required fields: '
                                  'admin email, and admin phone!')
        if admin_email == 'admin@example.com':
            raise ValidationError('Please set your real email address, not admin@example.com.')
        url = urljoin(self.get_param('api_url'), 'subscription')
        try:
            res = requests.post(url,
                json={
                    'name': self.get_param('company_name'),
                    'company_phone': self.env.user.company_id.partner_id.phone,
                    'company_email': self.env.user.company_id.partner_id.email,
                    'address_line1': self.env.user.company_id.partner_id.street,
                    'address_line2': self.env.user.company_id.partner_id.street2,
                    'city': self.env.user.company_id.partner_id.city,
                    'state_code': self.env.user.company_id.partner_id.state_id.code,
                    'state_name': self.env.user.company_id.partner_id.state_id.name,
                    'postal_code': self.env.user.company_id.partner_id.zip,
                    'country_code': self.env.user.company_id.partner_id.country_id.code,
                    'admin_name': self.get_param('admin_name'),
                    'admin_email': admin_email,
                    'admin_phone': admin_phone,
                    'odoo_url': self.get_param('web_base_url'),
                    'odoo_password': billing_password,
                    'odoo_version': release.major_version,
                    'odoo_db': self.env.cr.dbname,
                    'odoo_uid': billing_user.id,
                    'odoo_user': billing_user.login,
                    'module_version': self.get_param('module_version'),
                    'module_name': self.get_param('module_name'),
                    'promotion_code': self.get_param('discount_code'),
                    'partner_code': self.get_param('partner_code'),
                    'product_id': self.get_param('product_code'),
                },
                headers={
                    'x-instance-uid': self.get_param('instance_uid'),
                    'x-api-key': self.get_param('api_key') or '',
                })
            if not res.ok:
                raise ValidationError(res.text)
            data = res.json()
            # If this is the first subscription we must get an API key.
            if data.get('api_key'):
                self.env['ir.config_parameter'].sudo().set_param(
                    'connect.api_key', data['api_key'])
                self.env['ir.config_parameter'].sudo().set_param(
                    'connect.registration_id', data['registration_id'])
            self.set_param('is_subscribed', True)
            self.set_param('subscription_pricing', data['pricing'])
        except requests.exceptions.SSLError:
            raise ValidationError('Cannot connect to the Billing! Are you trying to connect to HTTP using HTTPS?')
        except Exception as e:
            raise ValidationError(e)

    def billing_session_url_action(self):
        api_url = self.get_param('api_url')
        instance_uid = self.get_param('instance_uid') or ''
        api_key = self.get_param('api_key') or ''
        locale = self.env['res.lang'].search(
            [('code','=', self.env.user.lang)]).iso_code
        res = requests.get(urljoin(api_url, 'customer'),
            json={
                'create_billing_session': True,
                'locale': locale,
                'module_name': MODULE_NAME,
            },
            headers={'x-instance-uid': instance_uid, 'x-api-key': api_key})
        if not res.ok:
            raise ValidationError(res.text)
        data = res.json()
        self.set_param('credits', data['credits'])
        # Set subscription status.
        self.set_param('is_subscribed', data['is_subscribed'])
        if data.get('is_subscribed') == False:
            self.env['connect.settings' ].connect_notify(
                title="Attention!",
                warning=True,
                sticky=True,
                message='Your subscription was cancelled!'
            )
        return {
            'type': 'ir.actions.act_url',
            'url': data.get('session_url')
        }

    def check_balance(self):
        api_url = self.get_param('api_url')
        instance_uid = self.get_param('instance_uid') or ''
        api_key = self.get_param('api_key') or ''
        res = requests.get(
            urljoin(api_url, 'balance'),
            json={'module_name': MODULE_NAME},
            headers={'x-instance-uid': instance_uid, 'x-api-key': api_key})
        if not res.ok:
            raise ValidationError(res.text)
        data = res.json()
        self.set_param('credits', data['balance'])
        self.set_param('subscription_pricing', data.get('pricing'))
        self.set_param('is_subscribed', data.get('is_subscribed'))
        if data.get('is_subscribed') == False:
            self.env['connect.settings' ].connect_notify(
                title="Attention!",
                warning=True,
                sticky=True,
                message='Your subscription was cancelled!'
            )
        # Check Twilio balance
        twilio_balance = None
        try:
            client = self.get_client()
            balance_data = client.api.account.balance.fetch()
            self.set_param('twilio_balance', balance_data.balance)
            twilio_balance = balance_data.balance
            self.env['connect.settings' ].connect_notify(
                title="Current Balance",
                message='Connect Credits: {}<br/>Twilio Balance: {}'.format(data['balance'], twilio_balance))
        except Exception as e:
            if 'Credentials are required to create a TwilioClient' in str(e):
                raise ValidationError('You must enter your Twilio auth / api keys!')
            elif 'Unable to fetch record:' in str(e):
                self.env['connect.settings' ].connect_notify(
                    title="Unable to fetch balance from subaccount!", message='')
            else:
                raise

    def unsubscribe_product(self):
        api_url = self.get_param('api_url')
        url = urljoin(api_url, 'subscription')
        res = requests.delete(url,
            json={
                'module_name': self.get_param('module_name'),
            },
            headers={
                'x-instance-uid': self.get_param('instance_uid') or '',
                'x-api-key': self.get_param('api_key') or ''
            })
        if not res.ok:
            raise ValidationError(res.text)
        else:
            self.set_param('is_subscribed', False)
            self.set_param('subscription_pricing', False)
            logger.info('Unsubscribe result: %s', res.text)
            # This is checked in the wizard to show the notification dialog.
            return True

    def update_billing_data(self):
        if not self.get_param('is_registered'):
            raise ValidationError('Not registered!')
        # Change also billing user password.
        billing_user = self.env.ref(BILLING_USER)
        billing_password = str(uuid.uuid4()) + '1!A'
        billing_user.password = billing_password
        self.env.cr.commit()
        api_url = self.get_param('api_url')
        url = urljoin(api_url, 'subscription')
        res = requests.put(url,
            json={
                'name': self.get_param('company_name'),
                'admin_name': self.get_param('admin_name'),
                'admin_email': self.get_param('admin_email'),
                'admin_phone': self.get_param('admin_phone'),
                'company_phone': self.env.user.company_id.partner_id.phone,
                'company_email': self.env.user.company_id.partner_id.phone,
                'address_line1': self.env.user.company_id.partner_id.street,
                'address_line2': self.env.user.company_id.partner_id.street2,
                'city': self.env.user.company_id.partner_id.city,
                'state_code': self.env.user.company_id.partner_id.state_id.code,
                'state_name': self.env.user.company_id.partner_id.state_id.name,
                'postal_code': self.env.user.company_id.partner_id.zip,
                'country_code': self.env.user.company_id.partner_id.country_id.code,
                'odoo_url': self.get_param('web_base_url'),
                'odoo_password': billing_password,
                'odoo_version': release.major_version,
                'odoo_db': self.env.cr.dbname,
                'module_version': self.get_param('module_version'),
                'odoo_uid': billing_user.id,
                'odoo_user': billing_user.login,
                'module_name': MODULE_NAME,
            },
            headers={
                'x-instance-uid': self.get_param('instance_uid'),
                'x-api-key': self.get_param('api_key')
            })
        if not res.ok:
            raise ValidationError(res.text)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Status",
                'message': 'Billing data updated',
                'sticky': False,
                'type': 'info',
            }
        }

    def add_credits(self):
        # Fetch formula from the billing
        if not self.get_param('is_registered'):
            raise ValidationError('Not registered!')
        api_url = self.get_param('api_url')
        url = urljoin(api_url, 'balance')
        res = requests.get(url,
            json={
                'module_name': self.get_param('module_name'),
                'balance_history': True,
            },
            headers={
                'x-instance-uid': self.get_param('instance_uid') or '',
                'x-api-key': self.get_param('api_key') or ''
            })
        if not res.ok:
            raise ValidationError(res.text)
        data = res.json()
        if data['monthly_average'] == 0:
            raise ValidationError('You can add credits only after one month of using the subscription!')
        context = {
            'default_pay_amount': data['monthly_average'] * 12,
            'default_formula': data['formula'],
            'default_monthly_average': data['monthly_average'],
        }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'connect.add_credits_wizard',
            'view_mode': 'form',
            'name': 'Add Credits Wizard',
            'target': 'new',
            'context': context,
        }

    @api.constrains('webhook_region', 'webhook_fallback_region')
    def _check_regions(self):
        if self.webhook_region == self.webhook_fallback_region:
            raise ValidationError('Regions must differ!')

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

    def get_pricing(self):
        api_url = self.get_param('api_url')
        url = urljoin(api_url, 'subscription')
        res = requests.get(url,
            json={
                'module_name': self.get_param('module_name'),
            },
            headers={
                'x-instance-uid': self.get_param('instance_uid') or '',
                'x-api-key': self.get_param('api_key') or ''
            })
        if not res.ok:
            raise ValidationError(res.text)
        else:
            self.set_param('subscription_pricing', res.json().get('pricing'))


####################################################################################

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
        if not rec.is_subscribed:
            return self.open_billing_form()
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

    def open_billing_form(self):
        rec = self.search([])
        if not rec:
            rec = self.sudo().with_context(no_constrains=True).create({})
        else:
            rec = rec[0]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'connect.settings',
            'res_id': rec.id,
            'name': 'Billing',
            'view_mode': 'form',
            'view_type': 'form',
            'view_id': self.env.ref('connect.connect_billing_form').id,
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
            self.check_access_rights('read')
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

    def change_billing_region(self):
        client = self.env['connect.settings'].get_client()
        # Update apps.
        for app in self.env['connect.twiml'].search([]):
            app.update_twilio_app(client)
        # Update domains
        for domain in self.env['connect.domain'].search([]):
            domain.update_twilio_domain(client)
        # Update numbers.
        for number in self.env['connect.number'].search([]):
            number.update_twilio_number(client)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Connect",
                'message': 'Billing region has been set!',
                'sticky': False,
                'type': 'info',
            }
        }

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
        status_url = urljoin(api_url, 'twilio/webhook/{}/callstatus'.format(instance_uid))
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

    def post_subscribe_product(self):
        try:
            self.sync()
        except Exception as e:
            logger.error('Could not sync the settings: %s', e)

    @api.onchange('transcript_calls')
    def _require_openai_key(self):
        if not self.sudo().get_param('openai_api_key'):
            raise ValidationError('You must set OpenAI key first!')