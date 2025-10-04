# -*- coding: utf-8 -*-
import inspect
import json
import logging
import os

import httpx
import openai
import requests
import random
import re
import string
from urllib.parse import urljoin
import uuid
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError, UserError
from twilio.rest import Client

logger = logging.getLogger(__name__)

TWILIO_LOG_LEVEL = logging.WARNING

############### SETTINGS #####################################
MODULE_NAME = "connect"
MAX_EXTEN_LEN = 4
PROTECTED_FIELDS = [
    "display_auth_token",
    "display_twilio_api_secret",
    "display_openai_api_key",
]

TWILIO_EDGES = [
    ('ashburn', 'US East Coast (Virginia)'),
    ('umatilla', 'US West Coast (Oregon)'),
    ('sydney', 'Australia'),
    ('sao-paulo', 'Brazil'),
    ('dublin', 'Ireland'),
    ('frankfurt', 'Frankfurt'),
    ('tokyo', 'Japan'),
    ('singapore', 'Singapore'),
    ('sydney', 'Australia'),
]


def debug(rec, message, level="info"):
    caller_module = inspect.stack()[1][3]
    if level == "info":
        fun = logger.info
    elif level == "warning":
        fun = logger.warning
        fun("++++++ {}: {}".format(caller_module, message))
    elif level == "error":
        fun = logger.error
        fun("++++++ {}: {}".format(caller_module, message))
    if rec.env["connect.settings"].sudo().get_param("debug_mode"):
        rec.env["connect.debug"].sudo().create(
            {
                "model": str(rec),
                "message": caller_module + ": " + message,
            }
        )
        if level == "info":
            fun("++++++ {}: {}".format(caller_module, message))


def format_connect_response(text):
    if not isinstance(text, str):
        text = str(text)
    symbol_pattern = re.compile(r"(\x08.)|\x08")
    text = symbol_pattern.sub("", text)
    color_pattern = re.compile(r"\x1b\[[\d;]+m")
    text = color_pattern.sub("", text)
    return text


def generate_password():
    characters = [
        random.choice(string.ascii_lowercase),
        random.choice(string.ascii_uppercase),
        random.choice(string.digits),
    ]
    characters += random.choices(string.ascii_letters + string.digits, k=20)
    random.shuffle(characters)
    return "".join(characters)


######### COPY FROM SETTINGS TO ELIMINATE CIRULAR IMPORT
def strip_number(number):
    """Strip number formating"""
    if not isinstance(number, str):
        return number
    pattern = r"[\s\(\)\-\+]"
    return re.sub(pattern, "", number).lstrip("0")


class Settings(models.Model):
    """One record model to keep all settings. The record is created on
    get_param / set_param methods on 1-st call.
    """

    _name = "connect.settings"
    _description = "Settings"

    name = fields.Char(compute="_get_name")
    debug_mode = fields.Boolean()
    twilio_auto_sync = fields.Boolean()
    twilio_region = fields.Selection([
        ('us1', 'US East (Virginia)'),
        ('ie1', 'Ireland (Dublin)'),
        ('au1', 'Australia (Sydney)'),
    ], default='us1', required=True)
    twilio_edge = fields.Selection(selection=TWILIO_EDGES)
    account_sid = fields.Char(string="Account SID")
    auth_token = fields.Char(
        groups="base.group_erp_manager,connect.group_connect_webhook"
    )
    display_auth_token = fields.Char()
    twilio_api_key = fields.Char()
    twilio_api_secret = fields.Char(groups="base.group_erp_manager")
    display_twilio_api_secret = fields.Char()
    twilio_balance = fields.Char(readonly=True)
    openai_api_key = fields.Char(groups="base.group_erp_manager")
    display_openai_api_key = fields.Char()
    number_search_operation = fields.Selection(
        [("=", "Equal"), ("like", "Like")], default="=", required=True
    )
    ############# RECORDING & TRANSCRIPT FIELDS ##############################################
    proxy_recordings = fields.Boolean(
        help="Re-stream recordings using Odoo user auth.", default=True
    )
    transcript_calls = fields.Boolean()
    transcript_provider = fields.Selection(selection=[('openai', 'Open AI')], default='openai', required=True)
    summary_prompt = fields.Text(required=True, default="Summarise this phone call")
    register_summary = fields.Boolean(
        default=True, help="Register summary at partner of reference chat."
    )
    ############################################################
    instance_uid = fields.Char("Instance UID", compute="_get_instance_data")
    api_url = fields.Char("API URL", compute="_get_instance_data")
    api_fallback_url = fields.Char("API Fallback URL")
    twilio_verify_requests = fields.Boolean(
        default=True, string="Verify Twilio Requests"
    )
    # Registration fields
    customer_code = fields.Char()
    registration_number = fields.Char(compute="_get_instance_data")
    registration_key = fields.Char("API Key", compute="_get_instance_data")
    is_registered = fields.Boolean()
    i_agree_to_register = fields.Boolean()
    i_agree_to_contact = fields.Boolean()
    i_agree_to_receive = fields.Boolean()
    installation_date = fields.Datetime(compute="_get_instance_data")
    module_version = fields.Char(compute="_get_instance_data")
    odoo_version = fields.Char(compute="_get_instance_data")
    admin_name = fields.Char()
    admin_phone = fields.Char()
    admin_email = fields.Char()
    company_name = fields.Char()
    company_email = fields.Char()
    company_phone = fields.Char()
    company_country = fields.Many2one('res.country')
    company_state_name = fields.Many2one('res.country.state', domain="[('country_id', '=?', company_country)]")
    company_city = fields.Char()
    web_base_url = fields.Char(compute="_get_instance_data", string="Odoo URL")
    latest_versions = fields.Html(readonly=True)

    def get_module_version(self, module_name):
        module = (
            self.env["ir.module.module"].sudo().search([("name", "=", module_name)])
        )
        module_version = (
            re.sub(r"^(\d+\.\d+\.)", "", module.installed_version) if module else ""
        )
        return module_version

    @staticmethod
    def get_module_list():
        return ["connect"]

    def check_latest_versions(self):
        module_list = self.get_module_list()
        request_data = {
            "instance_uid": self.get_param("instance_uid"),
            "odoo_version": release.major_version,
            "module_list": module_list,
        }
        response = self.make_usage_request(
            "check_versions", requests.post, data=request_data, raise_on_error=True
        )
        data = []
        for module in module_list:
            current_version = self.get_module_version(module)
            latest_version = response.get(module, "")
            data.append(
                {
                    "name": module,
                    "current_version": current_version,
                    "latest_version": latest_version,
                }
            )

        html = self.env["ir.ui.view"]._render_template(
            "connect.module_version_template", {"data": data}
        )
        self.set_param("latest_versions", html)

    def set_default_admin_and_company(self):
        self.company_email = self.env.user.company_id.email
        self.company_name = self.env.user.company_id.name
        self.company_phone = self.env.user.company_id.phone
        self.company_country = self.env.user.company_id.country_id
        self.company_city = self.env.user.company_id.city
        self.company_state_name = self.env.user.company_id.partner_id.state_id
        self.admin_name = self.env.user.partner_id.name
        self.admin_email = self.env.user.partner_id.email
        self.admin_phone = self.env.user.partner_id.phone

    def read(self, fields_to_read, load='_classic_read'):
        if not self.admin_name:
            self.set_default_admin_and_company()
        res = super(Settings, self).read(fields_to_read, load=load)
        return res

    def _get_instance_data(self):
        module = (
            self.env["ir.module.module"].sudo().search([("name", "=", MODULE_NAME)])
        )
        for rec in self:
            rec.module_version = re.sub(r"^(\d+\.\d+\.)", "", module.installed_version)
            rec.odoo_version = release.major_version
            rec.instance_uid = (
                self.env["ir.config_parameter"].sudo().get_param("connect.instance_uid")
            )
            # Format API URL according to the preferred region or dev URL.
            rec.installation_date = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("connect.installation_date")
            )
            rec.api_url = (
                self.env["ir.config_parameter"].sudo().get_param("connect.api_url")
            )
            rec.registration_key = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("connect.registration_key")
            )
            rec.web_base_url = (
                self.env["ir.config_parameter"].sudo().get_param("web.base.url")
            )
            rec.registration_number = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("connect.registration_number")
            )

    @api.model
    def connect_notify(
        self, message, title="Connect", notify_uid=None, sticky=False, warning=False
    ):
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
            self.env["bus.bus"].sendone(
                "connect_actions_{}".format(notify_uid),
                {
                    "action": "notify",
                    "message": message,
                    "title": title,
                    "sticky": sticky,
                    "warning": warning,
                },
            )
        else:
            self.env["bus.bus"]._sendone(
                "connect_actions_{}".format(notify_uid),
                "connect_notify",
                {
                    "message": message,
                    "title": title,
                    "sticky": sticky,
                    "warning": warning,
                },
            )

        return True

    @api.model
    def connect_reload_view(self, model):
        if release.version_info[0] < 15:
            msg = {
                "action": "reload_view",
                "model": model,
            }
            self.env["bus.bus"].sendone("connect_actions", json.dumps(msg))
        else:
            msg = {"model": model}
            self.env["bus.bus"]._sendone("connect_actions", "reload_view", msg)

    @api.model
    def set_defaults(self):
        # Called on installation to set default value
        api_url = self.get_param("api_url")
        if not api_url:
            # Set default value
            web_base_url = (
                self.env["ir.config_parameter"].sudo().get_param("web.base.url")
            )
            self.env["ir.config_parameter"].set_param("connect.api_url", web_base_url)
        installation_date = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("connect.installation_date")
        )
        if not installation_date:
            installation_date = fields.Datetime.now()
            self.env["ir.config_parameter"].set_param(
                "connect.installation_date", installation_date
            )

    @api.model
    def _get_name(self):
        for rec in self:
            rec.name = "General Settings"

    def open_settings_form(self):
        rec = self.search([])
        if not rec:
            rec = self.sudo().with_context(no_constrains=True).create({})
        else:
            rec = rec[0]
        return {
            "type": "ir.actions.act_window",
            "res_model": "connect.settings",
            "res_id": rec.id,
            "name": "General Settings",
            "view_mode": "form",
            "view_id": self.env.ref("connect.connect_settings_form").id,
            "target": "current",
        }

    @api.model
    # @ormcache('param')
    def get_param(self, param, default=False):
        """ """
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
        existing_uid = self.env["ir.config_parameter"].get_param("connect.instance_uid")
        if not existing_uid:
            if not instance_uid:
                instance_uid = str(uuid.uuid4())
            self.env["ir.config_parameter"].set_param(
                "connect.instance_uid", instance_uid
            )

    def register_instance(self):
        if not self.env.user.has_group("base.group_system"):
            raise ValidationError("Only Odoo admin can do it!")
        if self.get_param("is_registered"):
            raise ValidationError("This instance is already registered!")
        data = self.prepare_registration_data()
        if not data.get("customer_code"):
            raise ValidationError("Enter your customer code!")
        required_fields = [
            "admin_email",
            "admin_name",
            "admin_phone",
            "company_name",
            "company_city",
            "company_email",
            "company_phone",
            "company_country_code",
            "company_country_name",
            "installation_date",
            "module_name",
            "module_version",
            "url",
            "odoo_version",
        ]
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValidationError(
                f"Missing required fields: {', '.join(missing_fields)}"
            )
        res = self.make_usage_request(
            "registration", requests.post, data=data, raise_on_error=True
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "connect.registration_key", res.get("registration_key")
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "connect.registration_number", res.get("registration_number")
        )
        self.set_param("is_registered", True)

    def prepare_registration_data(self):
        company_country = self.get_param("company_country")
        company_state_name = self.get_param("company_state_name")
        return {
            "instance_uid": self.get_param("instance_uid"),
            "company_name": self.get_param("company_name"),
            "company_country": company_country.name if company_country else False,
            "company_state_name": company_state_name.name if company_state_name else False,
            "company_country_code": company_country.code if company_country else False,
            "company_country_name": company_country.name if company_country else False,
            "company_email": self.get_param("company_email"),
            "company_city": self.get_param("company_city"),
            "company_phone": self.get_param("company_phone"),
            "admin_name": self.get_param("admin_name"),
            "admin_email": self.get_param("admin_email"),
            "admin_phone": self.get_param("admin_phone"),
            "module_version": self.get_param("module_version"),
            "module_name": MODULE_NAME,
            "odoo_version": self.get_param("odoo_version"),
            "odoo_full_version": release.version,
            "url": self.get_param("web_base_url"),
            "installation_date": self.get_param("installation_date").strftime(
                "%Y-%m-%d"
            ),
            "customer_code": self.get_param("customer_code"),
        }

    def get_usage_model_list(self):
        return [
            "call",
            "callflow",
            "domain",
            "exten",
            "message",
            "number",
            "outgoing_callerid",
            "recording",
            "twiml",
            "user",
        ]

    @api.model
    def update_usage(self):
        res = {
            "usage": {},
            "usage_errors": {},
        }
        for model in self.get_usage_model_list():
            try:
                res["usage"][model] = {
                    "count": self.env["connect.{}".format(model)].search_count([]),
                }
                if model == "call":
                    self.env.cr.execute("SELECT SUM(duration)/60 FROM connect_call")
                    call_minutes = self.env.cr.fetchall()[0][0]
                    res["usage"][model]["minutes"] = call_minutes
            except Exception as e:
                res["errors"][model] = str(e)
        data = self.prepare_registration_data()
        data.update(res)
        try:
            self.make_usage_request("usage", requests.post, data)
        except Exception as e:
            logger.exception("Usage error:")

    def make_usage_request(
        self, path, method, data={}, headers={}, raise_on_error=False
    ):
        url = self.env["ir.config_parameter"].get_param(
            "connect.registration_url", "https://api1.oduist.com/instance/"
        )
        if not url.endswith("/"):
            url = "{}/".format(url)
        res = None
        try:
            res = method(urljoin(url, path), json=data, headers=headers)
            if res.status_code == 200:
                res = res.json()
                if res.get("error"):
                    raise ValidationError(res["error"])
                return res
            else:
                raise ValidationError(res.text)
        except Exception as e:
            if raise_on_error:
                raise ValidationError(str(e))
            else:
                return {}

    @api.model_create_multi
    def create(self, vals_list):
        if release.version_info[0] >= 17:
            self.env.registry.clear_cache()
        else:
            self.clear_caches()
        return super(Settings, self).create(vals_list)

    def write(self, vals):
        if self.env.context.get("skip_protected_fields"):
            return super(Settings, self).write(vals)
        if not self.openai_api_key and vals.get("display_openai_api_key"):
            vals.update({"transcript_calls": True})
        res = super(Settings, self).write(vals)
        changed_fields = {}
        for field_name in PROTECTED_FIELDS:
            if vals.get(field_name):
                changed_fields.update(
                    {
                        field_name.replace("display_", ""): vals.get(field_name),
                        field_name: "*" * len(vals.get(field_name)),
                    }
                )
        if changed_fields:
            # Set keys user super access.
            self.with_context(skip_protected_fields=True).sudo().write(changed_fields)
        # Reset cache
        if release.version_info[0] >= 17:
            self.env.registry.clear_cache()
        else:
            self.clear_caches()

    @api.model
    def get_client(self):
        try:
            (
                self.check_access_rule("read")
                if release.version_info[0] < 18
                else self.check_access("read")
            )
            account_sid = self.sudo().get_param("account_sid")
            auth_token = self.sudo().get_param("auth_token")
            client = Client(account_sid, auth_token)
            twilio_region = self.sudo().get_param("twilio_region")
            if twilio_region:
                client.region = twilio_region
            twilio_edge = self.sudo().get_param("twilio_edge")
            if twilio_edge:
                client.edge = twilio_edge
            client.http_client.logger.setLevel(TWILIO_LOG_LEVEL)
            return client
        except Exception as e:
            if "Credentials are required to create a TwilioClient" in str(e):
                raise ValidationError("Set Twilio API keys first!")
            else:
                raise

    @api.model
    def get_openai_client(self):
        api_key = self.sudo().get_param('openai_api_key')
        if not api_key:
            return False
        if os.environ.get('OPENAI_PROXY'):
            client = openai.OpenAI(
                api_key=api_key, http_client=httpx.Client(proxy=os.environ.get('HTTPS_PROXY')))
        else:
            client = openai.OpenAI(api_key=api_key)
        return client

    def check_api_url(self):
        message = None
        if re.match(r"^http://", self.get_param("api_url")):
            message = "Invalid api url! Please use HTTPS instead of HTTP to ensure a secure connection!"
        if re.match(
            r"(http|https)://(localhost|127\.0\.0\.\d)(:\d+)?",
            self.get_param("api_url"),
        ):
            message = "Invalid api url! Localhost is not allowed! Please use a valid and secure domain!"
        if message:
            logger.warning(message)
        return message

    def sync(self):
        if not (
            self.sudo().get_param("account_sid") and self.sudo().get_param("auth_token")
        ):
            raise ValidationError("You must set account SID and Auth token!")
        api_url_check = self.check_api_url()
        if api_url_check:
            raise ValidationError(api_url_check)
        self.env["connect.twiml"].sync()
        self.env["connect.domain"].sync()
        self.env["connect.number"].sync()
        self.env["connect.outgoing_callerid"].sync()
        self.connect_notify("Sync complete.")

    # Called from the settings.
    def reformat_numbers_button(self):
        for rec in self.env["res.partner"].search([]):
            rec.phone = rec._normalize_phone(rec.phone)
            rec.mobile = rec._normalize_phone(rec.mobile)

    def compute_sip_uri(self, user):
        return "sip:{}".format(self.env.user.connect_user.uri)

    def get_external_call_route(self, number, callerId, status_url):
        twiml = """
        <Response>
            <Dial callerId="{}"><Number statusCallback='{}' statusCallbackEvent='initiated answered completed'>{}</Number></Dial>
        </Response>
        """.format(
            callerId, status_url, number
        )
        return twiml

    @api.model
    def originate_call(self, number, res_model=None, res_id=None, user=None):
        number = strip_number(number)
        if len(number) > MAX_EXTEN_LEN:
            number = "+{}".format(number)
        client = self.get_client()
        partner_id = False
        obj = self.env[res_model].browse(res_id)
        caller_name = ""
        if res_model == "res.partner":
            partner_id = res_id
            caller_name = obj.display_name
        elif hasattr(obj, "partner_id"):
            partner_id = obj.partner_id.id
            caller_name = obj.partner_id.display_name
        elif hasattr(obj, "partner"):
            partner_id = obj.partner.id
            caller_name = obj.partner.display_name
        # If user is not set use current user.
        if not user:
            user = self.env.user
        if not user.connect_user:
            raise ValidationError("User does not have a SIP username defined!")
        # Get the first ring channel for the user
        first_flow = self.env['connect.user_callflow'].search([
            ('user', '=', user.id), ('callflow_type', 'in', ['client', 'sip'])], order='prio', limit=1)
        if first_flow.callflow_type == 'sip':
            to = self.compute_sip_uri(user)
        else:
            to = (
                "client:{}?autoAnswer=yes&Partner={}&CallerName={}".format(
                    self.env.user.connect_user.uri, partner_id, caller_name
                )
            )
        if "client:" in to:
            # Strip + before sending as param.
            to += "&From={}".format(number.replace("+", ""))
        exten = self.env["connect.exten"].search([("number", "=", number)], limit=1)
        default_number = self.env["connect.outgoing_callerid"].search(
            [("is_default", "=", True)], limit=1
        )
        if exten:
            # Set callerID to user's extension.
            callerId = user.connect_user.exten.number
        elif user.connect_user.outgoing_callerid:
            callerId = user.connect_user.outgoing_callerid.number
        else:
            callerId = default_number.number
        api_url = self.sudo().get_param("api_url")
        instance_uid = self.sudo().get_param("instance_uid", "")
        edge = self.twilio_edge or self.env['connect.settings'].get_param('twilio_edge')
        status_url = urljoin(api_url, "twilio/webhook/callstatus#e={}".format(edge))
        if exten:
            # Internal call to an extension.
            twiml = exten.render()
        else:
            twiml = self.get_external_call_route(number, callerId, status_url)
        record = self.env.user.connect_user.record_calls
        record_status_url = urljoin(api_url, "twilio/webhook/recordingstatus#e={}".format(edge))
        channel = client.calls.create(
            twiml=twiml,
            to=to,
            from_=callerId,
            status_callback=status_url,
            record=record,
            recording_channels="dual",
            recording_status_callback=record_status_url,
            recording_status_callback_event=["completed"],
            status_callback_event=["initiated", "answered", "completed"],
        )
        self.env["connect.channel"].sudo().create(
            {
                "sid": channel.sid,
                "technical_direction": "outboubd-api",
                "caller_user": user.id,
                "caller_pbx_user": user.connect_user.id,
                "partner": partner_id,
                "called": number,
                "caller": callerId,
            }
        )

    @api.onchange("transcript_calls")
    def _require_openai_key(self):
        if not self.sudo().get_param("openai_api_key"):
            raise ValidationError("You must set OpenAI key first!")

    def action_open_system_parameters(self):
        if release.version_info[0] >= 18:
            view_mode = "list,form"
        else:
            view_mode = "tree,form"
        return {
            "type": "ir.actions.act_window",
            "name": "System Parameters",
            "res_model": "ir.config_parameter",
            "view_mode": view_mode,
            "target": "current",
            "context": {"search_default_key": "connect.api_url"},
        }
