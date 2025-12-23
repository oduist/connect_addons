# -*- coding: utf-8 -*-
import inspect
import json
import logging
import os
import random
import re
import string
import uuid
from urllib.parse import urljoin

import httpx
import openai
import requests
from odoo import api, fields, models, release
from odoo.exceptions import UserError, ValidationError
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
    ("ashburn", "US East Coast (Virginia)"),
    ("umatilla", "US West Coast (Oregon)"),
    ("dublin", "Ireland"),
    ("frankfurt", "Frankfurt"),
    ("sydney", "Australia"),
    ("sao-paulo", "Brazil"),
    ("tokyo", "Japan"),
    ("singapore", "Singapore"),
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


######### COPY FROM SETTINGS TO ELIMINATE CIRCULAR IMPORT
def strip_number(number):
    """Strip number formating"""
    if not isinstance(number, str):
        return number
    pattern = r"[\s\(\)\-\+]"
    return re.sub(pattern, "", number).lstrip("0")


CONNECT_MODULES = ["connect"]


class Settings(models.Model):
    """One record model to keep all settings. The record is created on
    get_param / set_param methods on 1-st call.
    """

    _name = "connect.settings"
    _description = "Settings"

    name = fields.Char(compute="_get_name")
    debug_mode = fields.Boolean()
    twilio_auto_sync = fields.Boolean(default=True)
    twilio_region = fields.Selection(
        [
            ("us1", "US East (Virginia)"),
            ("ie1", "Ireland (Dublin)"),
            ("au1", "Australia (Sydney)"),
        ],
        default="us1",
        required=True,
    )
    twilio_edge = fields.Selection(
        selection=TWILIO_EDGES, required=True, default="ashburn"
    )
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
    # License token for OPL-1 validation
    license_token = fields.Text(
        string="License Token",
        groups="base.group_erp_manager",
        help="JWT license token from oduist.com. Leave empty to use 30-day trial.",
    )
    number_search_operation = fields.Selection(
        [("=", "Equal"), ("like", "Like")], default="=", required=True
    )
    ############# RECORDING & TRANSCRIPT FIELDS ##############################################
    proxy_recordings = fields.Boolean(
        help="Re-stream recordings using Odoo user auth.", default=True
    )
    transcript_calls = fields.Boolean()
    transcript_provider = fields.Selection(
        selection=[("openai", "Open AI")], default="openai", required=True
    )
    summary_prompt = fields.Text(required=True, default="Summarise this phone call")
    register_summary = fields.Boolean(
        default=True, help="Register summary at partner of reference chat."
    )
    fetch_call_prices = fields.Boolean(
        default=False,
        string="Fetch Call Prices",
        help="Enable fetching call prices from Twilio API after call completion. May add delay to call processing.",
    )
    ############################################################
    instance_uid = fields.Char("Instance UID", compute="_get_instance_data")
    api_url = fields.Char("API URL", compute="_get_instance_data")
    api_fallback_url = fields.Char("API Fallback URL")
    twilio_verify_requests = fields.Boolean(
        default=True, string="Verify Twilio Requests"
    )
    # Registration fields
    registration_number = fields.Char(compute="_get_instance_data")
    is_registered = (
        fields.Boolean()
    )  # TODO: Remove after upgrades, not needed any more.
    i_agree_to_contact = fields.Boolean(
        string="I agree to be contacted",
        help="Allow Oduist to contact you regarding critical security issues "
        "or problems with installed Connect modules.",
    )
    i_agree_to_receive = fields.Boolean(
        string="I agree to receive onboarding and updates",
        help="Subscribe to receive installation assistance (onboarding), "
        "new version announcements, and product updates.",
    )
    module_version = fields.Char(compute="_get_instance_data")
    odoo_version = fields.Char(compute="_get_instance_data")
    admin_email = fields.Char(
        help="It is required to contact this instance administrator by email in case any non-critical vulnerabilities are found in the application."
    )
    company_country = fields.Many2one(
        "res.country",
        help="We use the company’s country information for statistical tracking of our product installations by country.",
    )

    call_duration_limit = fields.Integer(
        compute="_get_instance_data", string="Call Duration Limit (seconds)"
    )
    connect_modules = fields.Many2many(
        "ir.module.module",
        string="Connect Modules",
        compute="_compute_connect_modules",
    )
    all_modules_purchased = fields.Boolean(
        compute="_compute_connect_modules",
    )

    def _compute_connect_modules(self):
        for rec in self:
            modules = (
                self.env["ir.module.module"]
                .sudo()
                .search([("name", "in", CONNECT_MODULES), ("state", "=", "installed")])
            )
            rec.connect_modules = modules
            rec.all_modules_purchased = all(
                m.oduist_module_purchased for m in modules
            )

    def _get_instance_data(self):
        module = (
            self.env["ir.module.module"].sudo().search([("name", "=", MODULE_NAME), ("state", "=", "installed")])
        )
        for rec in self:
            rec.module_version = re.sub(r"^(\d+\.\d+\.)", "", module.installed_version)
            rec.odoo_version = release.major_version
            rec.instance_uid = (
                self.env["ir.config_parameter"].sudo().get_param("connect.instance_uid")
            )
            # Format API URL according to the preferred region or dev URL.
            rec.api_url = (
                self.env["ir.config_parameter"].sudo().get_param("connect.api_url")
            )
            rec.registration_number = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("connect.registration_number") or 'Unregistered'
            )
            rec.call_duration_limit = int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("connect.call_duration_limit", "240")
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
        api_url = self.env["ir.config_parameter"].get_param("connect.api_url")
        if not api_url:
            # Set default value
            web_base_url = (
                self.env["ir.config_parameter"].sudo().get_param("web.base.url")
            )
            self.env["ir.config_parameter"].set_param("connect.api_url", web_base_url)
        
        # Set instance UID if not exists
        existing_uid = self.env["ir.config_parameter"].get_param("connect.instance_uid")
        if not existing_uid:
            instance_uid = str(uuid.uuid4())
            self.env["ir.config_parameter"].set_param(
                "connect.instance_uid", instance_uid
            )

    @api.model
    def _get_name(self):
        for rec in self:
            rec.name = "Connect Settings"

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

    def open_license_form(self):
        rec = self.search([])
        if not rec:
            rec = self.sudo().with_context(no_constrains=True).create({})
        else:
            rec = rec[0]
        return {
            "type": "ir.actions.act_window",
            "res_model": "connect.settings",
            "res_id": rec.id,
            "name": "License",
            "view_mode": "form",
            "view_id": self.env.ref("connect.connect_license_form").id,
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

        # Update license status if agreement fields changed
        agreement_fields = {"i_agree_to_contact", "i_agree_to_receive", "admin_email"}
        if any(field in vals for field in agreement_fields):
            self.env["connect.license"].update_license_status()

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
        api_key = self.sudo().get_param("openai_api_key")
        if not api_key:
            return False
        if os.environ.get("OPENAI_PROXY"):
            client = openai.OpenAI(
                api_key=api_key,
                http_client=httpx.Client(proxy=os.environ.get("HTTPS_PROXY")),
            )
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
        try:
            self.env["connect.twiml"].sync()
            self.env["connect.domain"].sync()
            self.env["connect.number"].sync()
            self.env["connect.outgoing_callerid"].sync()
            self.env["connect.whatsapp_sender"].sync()
            self.env["connect.message_content_template"].sync()
        except Exception as e:
            if "errors/20003" in str(e):
                raise ValidationError(
                    "Error authenticating requests to the Twilio API! Check your Auth Key!"
                )
            else:
                raise

    # Called from the settings.
    def reformat_numbers_button(self):
        for rec in self.env["res.partner"].search([]):
            rec.phone = rec._normalize_phone(rec.phone)
            rec.mobile = rec._normalize_phone(rec.mobile)

    def compute_sip_uri(self, user):
        return "sip:{}".format(self.env.user.connect_user.uri)

    def get_external_call_route(self, number, callerId, status_url):
        call_duration_limit = int(self.sudo().get_param("call_duration_limit"))
        twiml = """
        <Response>
            <Dial callerId="{}" timeLimit="{}"><Number statusCallback='{}' statusCallbackEvent='initiated answered completed'>{}</Number></Dial>
        </Response>
        """.format(callerId, call_duration_limit, status_url, number)
        return twiml

    @api.model
    def originate_call(
        self, number, res_model=None, res_id=None, user=None, whatsapp_call=False
    ):
        number = strip_number(number)
        if len(number) > MAX_EXTEN_LEN:
            number = "+{}".format(number)
        client = self.get_client()
        partner_id = False
        obj = self.env[res_model].browse(res_id) if res_model and res_id else False
        caller_name = ""
        if res_model == "res.partner" and obj:
            partner_id = res_id
            caller_name = obj.display_name
        elif obj and hasattr(obj, "partner_id") and obj.partner_id:
            partner_id = obj.partner_id.id
            caller_name = obj.partner_id.display_name
        elif obj and hasattr(obj, "partner") and obj.partner:
            partner_id = obj.partner.id
            caller_name = obj.partner.display_name
        # If user is not set use current user.
        if not user:
            user = self.env.user
        if not user.connect_user:
            raise ValidationError("User does not have a SIP username defined!")
        # Get the first ring channel for the user
        first_flow = self.env["connect.user_callflow"].search(
            [("user", "=", user.id), ("callflow_type", "in", ["client", "sip"])],
            order="prio",
            limit=1,
        )
        if first_flow.callflow_type == "sip":
            to = self.compute_sip_uri(user)
        else:
            to = "client:{}?autoAnswer=yes&Partner={}&CallerName={}".format(
                self.env.user.connect_user.uri, partner_id or "", caller_name or ""
            )
        if "client:" in to:
            # Strip + before sending as param.
            to += "&From={}".format((number or "").replace("+", ""))
        exten = self.env["connect.exten"].search([("number", "=", number)], limit=1)
        api_url = self.sudo().get_param("api_url")
        edge = self.twilio_edge or self.env["connect.settings"].get_param("twilio_edge")
        status_url = urljoin(api_url, "twilio/webhook/callstatus#e={}".format(edge))
        # Resolve callerId
        if exten:
            # Internal call to an extension.
            callerId = user.connect_user.exten.number
            twiml = exten.render()
        else:
            if whatsapp_call:
                # WhatsApp callerId selection akin to domain.originate_whatsapp_call
                pbx_user = user.connect_user
                sender = self.env["connect.whatsapp_sender"].get_default_sender(
                    pbx_user
                )
                caller_number = sender.number if sender else False
                if not caller_number:
                    raise ValidationError("You must configure a WhatsApp sender!")
                callerId = f"whatsapp:{caller_number}"
                # Build WhatsApp Dial
                call_duration_limit = int(self.sudo().get_param("call_duration_limit"))
                record_attrs = 'record=""' if pbx_user.record_calls else ""
                twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial callerId="{}">
        <WhatsApp statusCallback="{}" statusCallbackEvent="ringing answered completed">{}</WhatsApp>
    </Dial>
</Response>""".format(callerId, status_url, number)
            else:
                # Regular phone call
                default_number = self.env["connect.outgoing_callerid"].search(
                    [("is_default", "=", True)], limit=1
                )
                if user.connect_user.outgoing_callerid:
                    callerId = user.connect_user.outgoing_callerid.number
                else:
                    callerId = default_number.number
                twiml = self.get_external_call_route(number, callerId, status_url)
        record = self.env.user.connect_user.record_calls
        record_status_url = urljoin(
            api_url, "twilio/webhook/recordingstatus#e={}".format(edge)
        )
        debug(self, "Originate destination TwiML: {}".format(twiml))
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

    @api.onchange("twilio_region")
    def _reset_twilio_edge(self):
        if self.twilio_region == "us1":
            self.twilio_edge = "ashburn"
        elif self.twilio_region == "ie1":
            self.twilio_edge = "dublin"
        elif self.twilio_region == "au1":
            self.twilio_edge = "sydney"

    def get_twilio_balance(self):
        """Fetch current Twilio account balance"""
        try:
            client = self.get_client()

            # Try to fetch balance using the balance resource
            try:
                balance_item = client.api.v2010.account.balance.fetch()
                currency = getattr(balance_item, "currency", "USD")
                balance_value = getattr(balance_item, "balance", "0.00")
                balance = f"${balance_value} {currency}"
            except Exception as balance_error:
                # If balance API is not available (404 error), show informative message
                if (
                    "20404" in str(balance_error)
                    or "not found" in str(balance_error).lower()
                ):
                    balance = "Balance API not available for this account"
                    self.set_param("twilio_balance", balance)
                    self.connect_notify(
                        f"Twilio Balance: {balance}. The balance endpoint may not be available for your account type or region.",
                        title="Balance Info",
                    )
                    return balance
                else:
                    raise balance_error

            self.set_param("twilio_balance", balance)
            self.connect_notify(f"Twilio Balance: {balance}", title="Balance Update")
            return balance
        except Exception as e:
            error_msg = f"Failed to fetch Twilio balance: {str(e)}"
            self.connect_notify(error_msg, title="Balance Error", warning=True)
            raise ValidationError(error_msg)

    def update_license_status(self):
        """Check license status with license server."""
        return self.env["connect.license"].update_license_status()

    def buy_oduist_licenses(self):
        """Initiate purchase process for all Connect modules (excluding already purchased)."""
        License = self.env["connect.license"]
        token = self.sudo().get_param("license_token")
        if not token:
            License.update_license_status()
            token = self.sudo().get_param("license_token")

        token_data = License.validate_token(token) if token else None
        purchased_modules = (
            token_data.get("purchased_modules", {}) if token_data else {}
        )

        modules_to_buy = [m for m in CONNECT_MODULES if m not in purchased_modules]
        if not modules_to_buy:
            self.connect_notify("All modules are already purchased!", title="License")
            return

        return License.buy_licenses(modules_to_buy)
