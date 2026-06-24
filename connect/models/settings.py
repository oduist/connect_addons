# -*- coding: utf-8 -*-
"""
ODUIST PROPRIETARY LICENSE
Copyright (c) 2025 Oduist

This file contains license validation logic.
Modification is prohibited under Oduist Proprietary License.
See LICENSE and COPYRIGHT files for full terms.
"""

import inspect
import json
import logging
import os
import random
import re
import string
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import openai
import requests
from odoo import api, fields, models, release
from odoo.exceptions import ValidationError
from twilio.rest import Client
from twilio.http.http_client import TwilioHttpClient
from . import s3_utils
from odoo.addons.connect.models.license import ODUIST_MODULES
ODUIST_MODULES.append('connect')

logger = logging.getLogger(__name__)

TWILIO_LOG_LEVEL = logging.WARNING

MAX_EXTEN_LEN = 4

PROTECTED_FIELDS = [
    "display_auth_token",
    "display_region_auth_token",
    "display_twilio_api_secret",
    "display_openai_api_key",
    "display_aws_secret_access_key",
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

DEFAULT_SIP_DOMAIN_SUFFIX = 'sip.twilio.com'
DEFAULT_HOLD_MUSIC_URL = (
    'http://twimlets.com/holdmusic?Bucket=com.twilio.music.classical'
)


class _RewriteHostHttpClient(TwilioHttpClient):
    """Route Twilio SDK REST calls to a Twilio-compatible voice API host."""

    def __init__(self, rewrite_host, **kwargs):
        super().__init__(**kwargs)
        self._rewrite_host = rewrite_host

    def request(self, method, url, params=None, data=None, headers=None,
                auth=None, timeout=None, allow_redirects=False):
        url = urlunsplit(urlsplit(url)._replace(netloc=self._rewrite_host))
        return super().request(method, url, params, data, headers, auth,
                               timeout, allow_redirects)


SYSTEM_VOICE_CHOICES = [
    # Basic voices (no SSML support, free)
    ('man', 'Man (Basic)'),
    ('woman', 'Woman (Basic)'),
    # Amazon Polly - Arabic
    ('Polly.Zeina', 'Zeina (ar)'),
    ('Polly.Hala-Neural', 'Hala Neural (ar-AE)'),
    # Amazon Polly - Catalan
    ('Polly.Arlet-Neural', 'Arlet Neural (ca-ES)'),
    # Amazon Polly - Chinese
    ('Polly.Hiujin-Neural', 'Hiujin Neural (yue-CN)'),
    ('Polly.Zhiyu-Neural', 'Zhiyu Neural (cmn-CN)'),
    # Amazon Polly - Czech
    ('Polly.Jitka-Neural', 'Jitka Neural (cs-CZ)'),
    # Amazon Polly - Danish
    ('Polly.Sofie-Neural', 'Sofie Neural (da-DK)'),
    # Amazon Polly - Dutch
    ('Polly.Laura-Generative', 'Laura Generative (nl-NL)'),
    ('Polly.Lisa-Generative', 'Lisa Generative (nl-BE)'),
    # Amazon Polly - English (AU)
    ('Polly.Olivia-Long-Form', 'Olivia Long-Form (en-AU)'),
    # Amazon Polly - English (GB)
    ('Polly.Amy-Generative', 'Amy Generative (en-GB)'),
    ('Polly.Brian-Neural', 'Brian Neural (en-GB)'),
    # Amazon Polly - English (IN)
    ('Polly.Aditi-Generative', 'Aditi Generative (en-IN)'),
    # Amazon Polly - English (IE)
    ('Polly.Niamh-Generative', 'Niamh Generative (en-IE)'),
    # Amazon Polly - English (NZ)
    ('Polly.Aria-Generative', 'Aria Generative (en-NZ)'),
    # Amazon Polly - English (SG)
    ('Polly.Jasmine-Generative', 'Jasmine Generative (en-SG)'),
    # Amazon Polly - English (ZA)
    ('Polly.Ayanda-Generative', 'Ayanda Generative (en-ZA)'),
    # Amazon Polly - English (US)
    ('Polly.Danielle-Generative', 'Danielle Generative (en-US)'),
    ('Polly.Gregory-Generative', 'Gregory Generative (en-US)'),
    ('Polly.Joanna-Generative', 'Joanna Generative (en-US)'),
    ('Polly.Matthew-Generative', 'Matthew Generative (en-US)'),
    ('Polly.Ruth-Neural', 'Ruth Neural (en-US)'),
    ('Polly.Salli-Generative', 'Salli Generative (en-US)'),
    ('Polly.Stephen-Neural', 'Stephen Neural (en-US)'),
    # Amazon Polly - English (Welsh)
    ('Polly.Geraint', 'Geraint (en-WL)'),
    # Amazon Polly - Finnish
    ('Polly.Suvi-Neural', 'Suvi Neural (fi-FI)'),
    # Amazon Polly - French
    ('Polly.Lea-Generative', 'Léa Generative (fr-FR)'),
    ('Polly.Remi-Generative', 'Rémi Generative (fr-FR)'),
    # Amazon Polly - French (Belgian)
    ('Polly.Isabelle-Generative', 'Isabelle Generative (fr-BE)'),
    # Amazon Polly - French (Canadian)
    ('Polly.Gabrielle-Neural', 'Gabrielle Neural (fr-CA)'),
    ('Polly.Liam-Neural', 'Liam Neural (fr-CA)'),
    # Amazon Polly - German
    ('Polly.Vicki-Generative', 'Vicki Generative (de-DE)'),
    ('Polly.Daniel-Generative', 'Daniel Generative (de-DE)'),
    # Amazon Polly - German (Austrian)
    ('Polly.Hannah-Generative', 'Hannah Generative (de-AT)'),
    # Amazon Polly - German (Swiss)
    ('Polly.Sabrina-Generative', 'Sabrina Generative (de-CH)'),
    # Amazon Polly - Hindi (Kajal also supports en-IN)
    ('Polly.Kajal-Neural', 'Kajal Neural (hi-IN)'),
    # Amazon Polly - Icelandic
    ('Polly.Dora-Neural', 'Dóra Neural (is-IS)'),
    ('Polly.Karl-Neural', 'Karl Neural (is-IS)'),
    # Amazon Polly - Italian
    ('Polly.Bianca-Generative', 'Bianca Generative (it-IT)'),
    ('Polly.Adriano-Neural', 'Adriano Neural (it-IT)'),
    # Amazon Polly - Japanese
    ('Polly.Kazuha-Neural', 'Kazuha Neural (ja-JP)'),
    ('Polly.Tomoko-Neural', 'Tomoko Neural (ja-JP)'),
    # Amazon Polly - Korean
    ('Polly.Seoyeon-Generative', 'Seoyeon Generative (ko-KR)'),
    # Amazon Polly - Norwegian
    ('Polly.Liv-Neural', 'Liv Neural (nb-NO)'),
    # Amazon Polly - Polish
    ('Polly.Ola-Generative', 'Ola Generative (pl-PL)'),
    # Amazon Polly - Portuguese (BR)
    ('Polly.Camila-Generative', 'Camila Generative (pt-BR)'),
    ('Polly.Thiago-Neural', 'Thiago Neural (pt-BR)'),
    # Amazon Polly - Portuguese (EU)
    ('Polly.Ines-Neural', 'Inês Neural (pt-PT)'),
    # Amazon Polly - Romanian
    ('Polly.Carmen', 'Carmen (ro-RO)'),
    # Amazon Polly - Russian
    ('Polly.Tatyana', 'Tatyana (ru-RU)'),
    ('Polly.Maxim', 'Maxim (ru-RU)'),
    # Amazon Polly - Spanish (Spain)
    ('Polly.Lucia-Generative', 'Lucia Generative (es-ES)'),
    ('Polly.Sergio-Generative', 'Sergio Generative (es-ES)'),
    # Amazon Polly - Spanish (Mexican)
    ('Polly.Mia-Generative', 'Mia Generative (es-MX)'),
    ('Polly.Andres-Generative', 'Andrés Generative (es-MX)'),
    # Amazon Polly - Spanish (US)
    ('Polly.Lupe-Generative', 'Lupe Generative (es-US)'),
    ('Polly.Pedro-Neural', 'Pedro Neural (es-US)'),
    # Amazon Polly - Swedish
    ('Polly.Astrid-Neural', 'Astrid Neural (sv-SE)'),
    # Amazon Polly - Turkish
    ('Polly.Burcu-Neural', 'Burcu Neural (tr-TR)'),
    # Amazon Polly - Welsh
    ('Polly.Gwyneth', 'Gwyneth (cy-GB)'),
    # Google Chirp3-HD - languages not covered by Polly
    ('Google.bg-BG-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (bg-BG)'),
    ('Google.bn-IN-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (bn-IN)'),
    ('Google.et-EE-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (et-EE)'),
    ('Google.hr-HR-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (hr-HR)'),
    # Google Chirp3-HD - popular languages (alternative to Polly)
    ('Google.en-US-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (en-US)'),
    ('Google.en-GB-Chirp3-HD-Fenrir', 'Fenrir Chirp3-HD (en-GB)'),
    ('Google.de-DE-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (de-DE)'),
    ('Google.fr-FR-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (fr-FR)'),
    ('Google.es-ES-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (es-ES)'),
    ('Google.it-IT-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (it-IT)'),
    ('Google.ja-JP-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (ja-JP)'),
    ('Google.ko-KR-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (ko-KR)'),
    ('Google.nl-NL-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (nl-NL)'),
    ('Google.pl-PL-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (pl-PL)'),
    ('Google.pt-BR-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (pt-BR)'),
    ('Google.ru-RU-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (ru-RU)'),
    ('Google.sv-SE-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (sv-SE)'),
    ('Google.tr-TR-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (tr-TR)'),
    ('Google.da-DK-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (da-DK)'),
    ('Google.fi-FI-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (fi-FI)'),
    ('Google.nb-NO-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (nb-NO)'),
    ('Google.yue-HK-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (yue-HK)'),
    ('Google.cs-CZ-Chirp3-HD-Aoede', 'Aoede Chirp3-HD (cs-CZ)'),
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
    special_chars = "@!#$%^&*"
    characters = [
        random.choice(string.ascii_lowercase),
        random.choice(string.ascii_uppercase),
        random.choice(string.digits),
        random.choice(special_chars),
    ]
    characters += random.choices(string.ascii_letters + string.digits + special_chars, k=19)
    random.shuffle(characters)
    return "".join(characters)


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

    _name = "connect.settings"
    _description = "Settings"

    name = fields.Char(compute="_get_name")
    debug_mode = fields.Boolean()
    twilio_auto_sync = fields.Boolean(default=True)
    twilio_region = fields.Selection([
        ('us1', 'US'),
        ('ie1', 'Europe'),
        ('au1', 'Australia'),
    ], default='us1', required=True)
    twilio_edge = fields.Selection(selection=TWILIO_EDGES, required=True, default='ashburn')
    rest_api_host = fields.Char(
        string="REST API Host",
        help="Hostname of a Twilio-compatible voice API. Leave empty for Twilio. "
             "When set, SDK REST traffic uses this host; region/edge are ignored.",
    )
    sip_domain_suffix = fields.Char(
        string="SIP Domain Suffix",
        help="SIP hostname suffix (subdomain.suffix). Empty = sip.twilio.com.",
    )
    default_hold_music_url = fields.Char(
        string="Default Hold Music URL",
        help="Hold/wait music for conferences. Empty = Twilio twimlets default.",
    )
    webrtc_provider = fields.Selection(
        [
            ('twilio', 'Twilio WebRTC (browser phone)'),
            ('disabled', 'Disabled (SIP phones only)'),
        ],
        default='twilio',
        required=True,
        string="Browser Phone",
    )
    account_sid = fields.Char(string="Account SID")
    auth_token = fields.Char(
        groups="base.group_erp_manager,connect.group_connect_webhook"
    )
    display_auth_token = fields.Char()
    region_auth_token = fields.Char(
        groups="base.group_erp_manager,connect.group_connect_webhook"
    )
    display_region_auth_token = fields.Char()
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
    # ---- S3 recording storage (ODU-36) ----
    s3_recordings_enabled = fields.Boolean(
        string="Store recordings in S3",
        help="Turn on to configure and use AWS S3 storage (reveals the settings "
             "below). Recordings are read from S3 only once a bucket is configured "
             "and Twilio uploads there; otherwise they keep playing from Twilio.",
    )
    aws_access_key_id = fields.Char(string="AWS Access Key ID")
    aws_secret_access_key = fields.Char(
        string="AWS Secret Access Key", groups="base.group_erp_manager"
    )
    display_aws_secret_access_key = fields.Char()
    aws_region = fields.Selection(
        selection=[
            ("eu-central-1", "EU (Frankfurt)"),
            ("eu-west-1", "EU (Ireland)"),
            ("us-east-1", "US East (N. Virginia)"),
            ("us-west-2", "US West (Oregon)"),
            ("ap-southeast-1", "Asia Pacific (Singapore)"),
        ],
        string="AWS Region", default="eu-central-1", required=True,
    )
    aws_s3_bucket_prefix = fields.Char(
        string="S3 Bucket Prefix", default=lambda self: s3_utils.S3_BUCKET_PREFIX,
        help="Bucket names are forced to start with this prefix, and the IAM policy "
             "above is scoped to it. Default 'oduist-connect-'. Set your own to match "
             "an existing IAM naming convention (leave empty to use the default).",
    )
    aws_s3_bucket = fields.Char(
        string="S3 Bucket Name",
        help="The bucket name (or just a suffix). The prefix above is combined with "
             "it dynamically to form the full bucket name shown below.",
    )
    aws_s3_bucket_name = fields.Char(
        string="Full Bucket Name", compute="_compute_aws_s3_bucket_name", readonly=True,
        help="Actual bucket = prefix + name. Used for provisioning, the S3 URL and "
             "playback.",
    )
    aws_s3_prefix = fields.Char(string="S3 Folder (prefix)", default="recordings")
    s3_retention_days = fields.Integer(
        string="Retention (days)", default=0,
        help="0 = keep forever. >0 sets an S3 lifecycle rule that deletes the audio "
             "file after N days (the recording row and transcript are kept).",
    )
    aws_s3_url = fields.Char(
        string="S3 URL (paste into Twilio)", compute="_compute_aws_s3_url", readonly=True,
    )
    aws_iam_policy = fields.Text(
        string="AWS IAM Policy", compute="_compute_aws_iam_policy", readonly=True,
        help="Least-privilege policy to attach to the AWS IAM user whose access "
             "key you enter below. Copy it into IAM → Users → Add inline policy.",
    )
    twilio_aws_credential_sid = fields.Char(
        string="Twilio AWS Credential SID", readonly=True,
    )
    transcript_calls = fields.Boolean()
    transcript_provider = fields.Selection(
        selection=[("openai", "Open AI")], default="openai", required=True
    )
    summary_prompt = fields.Text(required=True, default="Summarise this phone call")
    register_summary = fields.Boolean(
        default=True, help="Register summary at partner of reference chat."
    )
    transcription_rules = fields.One2many('connect.transcription_rule', 'settings')
    transcript_voice_message = fields.Boolean(default=True)
    chatter_message_generate_prompt = fields.Text(
        default='Continue the conversation naturally!', string='Message Generate Prompt')
    fetch_call_prices = fields.Boolean(
        default=False,
        string="Fetch Call Prices",
        help="Enable fetching call prices from Twilio API after call completion. May add delay to call processing.",
    )
    ############################################################
    api_url = fields.Char("API URL", compute="_get_instance_data")
    api_fallback_url = fields.Char("API Fallback URL")
    twilio_verify_requests = fields.Boolean(
        default=True, string="Verify Twilio Requests"
    )
    call_duration_limit = fields.Integer(
        default=7200, string="Call Duration Limit (seconds)"
    )
    # Voice settings
    system_voice = fields.Selection(SYSTEM_VOICE_CHOICES, string='System Voice', default='man', required=True,
       help='Voice used for all system prompts (callflow messages, voicemail, transfers, etc.)')
    pronunciation_rules = fields.Text(
        string='Pronunciation Rules',
        help='JSON map of text to pronunciation substitutions (e.g., {"3CHI": "3-chee", "CEO": "C-E-O"})'
    )

    def _get_instance_data(self):
        for rec in self:
            api_url = (
                self.env["ir.config_parameter"].sudo().get_param("connect.api_url")
            )
            if not api_url:
                web_base_url = (
                    self.env["ir.config_parameter"].sudo().get_param("web.base.url")
                )
                self.env["ir.config_parameter"].sudo().set_param("connect.api_url", web_base_url)
                api_url = web_base_url
                # Reset webhook user password from the default value set in data file.
                user = self.env.ref("connect.user_connect_webhook")
                password = generate_password()
                user.write({'password': password})
            rec.api_url = api_url

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
    def _get_name(self):
        for rec in self:
            rec.name = "Connect Settings"

    # ---- S3 recording storage (ODU-36) ----
    @api.depends("aws_s3_bucket_name", "aws_region", "aws_s3_prefix")
    def _compute_aws_s3_url(self):
        for rec in self:
            if rec.aws_s3_bucket_name and rec.aws_region:
                rec.aws_s3_url = s3_utils.build_s3_url(
                    rec.aws_s3_bucket_name, rec.aws_region, rec.aws_s3_prefix
                )
            else:
                rec.aws_s3_url = False

    @api.depends("aws_s3_bucket", "aws_s3_bucket_prefix")
    def _compute_aws_s3_bucket_name(self):
        """Full bucket = prefix + name, derived dynamically (input is never mutated)."""
        for rec in self:
            rec.aws_s3_bucket_name = s3_utils.normalize_bucket_name(
                rec.aws_s3_bucket, rec._effective_s3_prefix()
            )

    def _effective_s3_prefix(self):
        """Configured bucket prefix, falling back to the module default."""
        self.ensure_one()
        return self.aws_s3_bucket_prefix or s3_utils.S3_BUCKET_PREFIX

    @api.depends("aws_s3_bucket_prefix")
    def _compute_aws_iam_policy(self):
        for rec in self:
            rec.aws_iam_policy = s3_utils.build_iam_policy(rec._effective_s3_prefix())

    def _get_s3_client(self):
        """boto3 S3 client built from the singleton settings (sudo to read secret)."""
        import boto3
        rec = self.env["connect.settings"].sudo().search([], limit=1)
        return boto3.client(
            "s3",
            aws_access_key_id=rec.aws_access_key_id,
            aws_secret_access_key=rec.aws_secret_access_key,
            region_name=rec.aws_region,
        )

    def action_provision_s3_bucket(self):
        from botocore.exceptions import ClientError
        self.ensure_one()
        if not (self.aws_s3_bucket and self.aws_region):
            raise ValidationError("Set S3 bucket name and region first.")
        s3 = self._get_s3_client()
        prefix = self._effective_s3_prefix()
        bucket = self.aws_s3_bucket_name
        try:
            if self.aws_region == "us-east-1":
                s3.create_bucket(Bucket=bucket)
            else:
                s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": self.aws_region},
                )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "AccessDenied":
                raise ValidationError(
                    "AWS denied s3:CreateBucket for '%s'. The '%s' prefix is added "
                    "automatically, so this usually means the IAM policy is not "
                    "attached to this key, or its Resource ARN uses a different "
                    "prefix. Allow s3:CreateBucket on 'arn:aws:s3:::%s*'.\n\n%s"
                    % (bucket, prefix, prefix, e)
                )
            if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise ValidationError("S3 create_bucket failed: %s" % e)
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )
        s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )
        if self.s3_retention_days and self.s3_retention_days > 0:
            s3.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration=s3_utils.build_lifecycle_config(
                    self.aws_s3_prefix, self.s3_retention_days
                ),
            )
        self.connect_notify("S3 bucket '%s' provisioned." % bucket, notify_uid=self.env.uid)
        return True

    def action_create_twilio_aws_credential(self):
        self.ensure_one()
        settings = self.env["connect.settings"].sudo()
        access_key = self.aws_access_key_id
        secret = settings.get_param("aws_secret_access_key")
        if not (access_key and secret):
            raise ValidationError("Set AWS access key and secret first.")
        sid = settings.get_param("account_sid")
        token = settings.get_param("auth_token")
        friendly = "connect-s3-recordings"
        base = "https://accounts.twilio.com/v1/Credentials/AWS"
        try:
            existing = requests.get(base, auth=(sid, token), timeout=30)
            existing.raise_for_status()
            for cred in existing.json().get("credentials", []):
                if cred.get("friendly_name") == friendly:
                    self.twilio_aws_credential_sid = cred["sid"]
                    self.connect_notify(
                        "Twilio AWS credential '%s' already exists: %s"
                        % (friendly, cred["sid"]),
                        notify_uid=self.env.uid,
                    )
                    return True
            resp = requests.post(
                base, auth=(sid, token), timeout=30,
                data={
                    "Credentials": "%s:%s" % (access_key, secret),
                    "FriendlyName": friendly,
                },
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ValidationError("Twilio AWS credential request failed: %s" % e)
        self.twilio_aws_credential_sid = resp.json()["sid"]
        self.connect_notify(
            "Twilio AWS credential created: %s" % self.twilio_aws_credential_sid,
            notify_uid=self.env.uid,
        )
        return True

    def action_recreate_twilio_aws_credential(self):
        """Delete the existing connect-s3-recordings credential and create a fresh
        one with the current AWS keys (Twilio can't update a credential's key).
        The new SID must be re-selected in the Twilio Console."""
        self.ensure_one()
        settings = self.env["connect.settings"].sudo()
        access_key = self.aws_access_key_id
        secret = settings.get_param("aws_secret_access_key")
        if not (access_key and secret):
            raise ValidationError("Set AWS access key and secret first.")
        sid = settings.get_param("account_sid")
        token = settings.get_param("auth_token")
        friendly = "connect-s3-recordings"
        base = "https://accounts.twilio.com/v1/Credentials/AWS"
        try:
            existing = requests.get(base, auth=(sid, token), timeout=30)
            existing.raise_for_status()
            for cred in existing.json().get("credentials", []):
                if cred.get("friendly_name") == friendly:
                    deleted = requests.delete(
                        "%s/%s" % (base, cred["sid"]), auth=(sid, token), timeout=30
                    )
                    deleted.raise_for_status()
            resp = requests.post(
                base, auth=(sid, token), timeout=30,
                data={
                    "Credentials": "%s:%s" % (access_key, secret),
                    "FriendlyName": friendly,
                },
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ValidationError("Twilio AWS credential request failed: %s" % e)
        self.twilio_aws_credential_sid = resp.json()["sid"]
        self.connect_notify(
            "Twilio AWS credential recreated: %s. Re-select it in Twilio Console "
            "→ Voice → Recordings → Settings." % self.twilio_aws_credential_sid,
            notify_uid=self.env.uid, sticky=True,
        )
        return True

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
        return res

    @api.model
    def uses_compatible_rest_api(self):
        return bool((self.get_param('rest_api_host') or '').strip())

    @api.model
    def normalized_sip_domain_suffix(self):
        suffix = (self.get_param('sip_domain_suffix') or '').strip().lstrip('.')
        return suffix or DEFAULT_SIP_DOMAIN_SUFFIX

    @api.model
    def format_sip_domain_name(self, subdomain):
        return '{}.{}'.format(subdomain, self.normalized_sip_domain_suffix())

    @api.model
    def format_sip_edge_domain(self, subdomain, edge):
        suffix = self.normalized_sip_domain_suffix()
        if suffix == DEFAULT_SIP_DOMAIN_SUFFIX and edge:
            return '{}.sip.{}.twilio.com'.format(subdomain, edge)
        return self.format_sip_domain_name(subdomain)

    @api.model
    def format_sip_connect_uri(self, username, subdomain, edge=None):
        suffix = self.normalized_sip_domain_suffix()
        if suffix == DEFAULT_SIP_DOMAIN_SUFFIX and edge and edge != 'roaming':
            return '{}@{}.sip.{}.twilio.com'.format(username, subdomain, edge)
        return '{}@{}'.format(username, self.format_sip_domain_name(subdomain))

    @api.model
    def get_default_hold_music_url(self):
        url = (self.get_param('default_hold_music_url') or '').strip()
        return url or DEFAULT_HOLD_MUSIC_URL

    @api.model
    def is_webrtc_enabled(self):
        return self.get_param('webrtc_provider') != 'disabled'

    @api.model
    def parse_sip_to_user(self, to_val):
        if not isinstance(to_val, str) or not to_val.startswith('sip:'):
            return None
        at = to_val.find('@')
        if at == -1:
            return None
        user_part = to_val[4:at]
        host_part = to_val[at + 1:]
        suffix = self.normalized_sip_domain_suffix()
        if suffix == DEFAULT_SIP_DOMAIN_SUFFIX:
            if re.match(r'^.+\.sip(\.[^.]+)?\.twilio\.com$', host_part):
                return user_part
        elif host_part == suffix or host_part.endswith('.' + suffix):
            return user_part
        return None

    @api.model
    def get_system_voice(self):
        """Get the system-wide voice setting for all TwiML say() calls"""
        voice = self.sudo().get_param('system_voice', 'man')
        return voice

    @api.model
    def process_pronunciation(self, text):
        """Process text to apply SSML pronunciation substitutions"""
        if not text:
            return text

        try:
            rules_json = self.sudo().get_param('pronunciation_rules')
            if not rules_json:
                return text

            rules = json.loads(rules_json)
            processed_text = text
            voice = self.get_system_voice()
            use_ssml = voice not in ('man', 'woman')
            has_substitutions = False

            for original, pronunciation in rules.items():
                pattern = re.compile(re.escape(original), re.IGNORECASE)
                if pattern.search(processed_text):
                    if use_ssml:
                        def replace_func(match):
                            return f'<sub alias="{pronunciation}">{match.group(0)}</sub>'
                        processed_text = pattern.sub(replace_func, processed_text)
                    else:
                        processed_text = pattern.sub(pronunciation, processed_text)
                    has_substitutions = True

            if has_substitutions and use_ssml:
                processed_text = f'<speak>{processed_text}</speak>'

            return processed_text

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f'Error processing pronunciation rules: {e}')
            return text

    @api.model
    def get_client(self, region=True):
        try:
            (
                self.check_access_rule("read")
                if release.version_info[0] < 18
                else self.check_access("read")
            )
            account_sid = self.sudo().get_param("account_sid")
            auth_token = self.sudo().get_param("auth_token")
            rest_api_host = (self.sudo().get_param("rest_api_host") or "").strip()
            token_to_use = auth_token
            if region and not rest_api_host:
                region_auth_token = self.sudo().get_param("region_auth_token")
                token_to_use = region_auth_token if region_auth_token else auth_token
            http_client = _RewriteHostHttpClient(rest_api_host) if rest_api_host else None
            client = Client(account_sid, token_to_use, http_client=http_client)
            if region and not rest_api_host:
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
        uri = "sip:{}".format(self.env.user.connect_user.uri)
        if user.connect_user.auto_answer_header:
            uri = f'{uri}?{user.connect_user.auto_answer_header}'
        return uri

    def get_external_call_route(self, number, callerId, status_url,
            record='do-not-record', record_status_url=None):
        call_duration_limit = int(self.sudo().get_param('call_duration_limit'))
        twiml = """
        <Response>
            <Dial record="{}" recordingStatusCallback="{}" callerId="{}" timeLimit="{}"><Number statusCallback='{}' statusCallbackEvent='initiated answered completed'>{}</Number></Dial>
        </Response>
        """.format(
            record, record_status_url, callerId, call_duration_limit, status_url, number
        )
        return twiml

    @api.model
    def originate_call(self, number, res_model=None, res_id=None, user=None, whatsapp_call=False):
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
        first_flow = self.env['connect.user_callflow'].search([
            ('user', '=', user.id), ('callflow_type', 'in', ['client', 'sip'])], order='prio', limit=1)
        if first_flow.callflow_type == 'sip':
            to = self.compute_sip_uri(user)
        else:
            to = (
                "client:{}?autoAnswer=yes&Partner={}&CallerName={}".format(
                    self.env.user.connect_user.uri, partner_id or '', caller_name or ''
                )
            )
        if "client:" in to:
            # Strip + before sending as param.
            to += "&From={}".format((number or '').replace("+", ""))
        exten = self.env["connect.exten"].search([("number", "=", number)], limit=1)
        api_url = self.sudo().get_param("api_url")
        edge = self.twilio_edge or self.env['connect.settings'].get_param('twilio_edge')
        status_url = urljoin(api_url, "twilio/webhook/callstatus#e={}".format(edge))
        record = 'record-from-answer-dual' if self.env.user.connect_user.record_calls else 'do-not-record'
        record_status_url = urljoin(api_url, "twilio/webhook/recordingstatus#e={}".format(edge))
        # Resolve callerId
        if exten:
            # Internal call to an extension.
            callerId = user.connect_user.exten.number
            twiml = exten.render()
        else:
            if whatsapp_call:
                # WhatsApp callerId selection akin to domain.originate_whatsapp_call
                pbx_user = user.connect_user
                sender = self.env['connect.whatsapp_sender'].get_default_sender(pbx_user)
                caller_number = sender.number if sender else False
                if not caller_number:
                    raise ValidationError("You must configure a WhatsApp sender!")
                callerId = f"whatsapp:{caller_number}"
                # Build WhatsApp Dial
                twiml = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
    <Dial callerId="{}" record="{}" recordingStatusCallback="{}">
        <WhatsApp statusCallback="{}" statusCallbackEvent="ringing answered completed">{}</WhatsApp>
    </Dial>
    </Response>""".format(callerId, record, record_status_url, status_url, number)
            else:
                # Regular phone call
                default_number = self.env["connect.outgoing_callerid"].search(
                    [("is_default", "=", True)], limit=1
                )
                if user.connect_user.outgoing_callerid:
                    callerId = user.connect_user.outgoing_callerid.number
                else:
                    callerId = default_number.number
                twiml = self.get_external_call_route(
                    number, callerId, status_url, record=record, record_status_url=record_status_url)
        debug(self, 'Originate destination TwiML: {}'.format(twiml))
        channel = client.calls.create(
            twiml=twiml,
            to=to,
            from_=callerId,
            status_callback=status_url,
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
