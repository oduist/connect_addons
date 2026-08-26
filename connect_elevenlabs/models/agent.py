# -*- coding: utf-8 -*-
import json
import logging

# Supress a warning message.
import warnings

import requests
from elevenlabs.core.api_error import ApiError
from elevenlabs.types import AgentPlatformSettingsRequestModel, ConversationalConfig
from odoo import api, fields, models, release
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml
from odoo.exceptions import ValidationError
from pydantic.warnings import PydanticDeprecatedSince20
from twilio.twiml.voice_response import Connect, VoiceResponse

warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)

logger = logging.getLogger(__name__)

language_list = [
    ("ar", "Arabic"),
    ("bg", "Bulgarian"),
    ("zh", "Chinese"),
    ("hr", "Croatian"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("nl", "Dutch"),
    ("en", "English"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("de", "German"),
    ("el", "Greek"),
    ("hi", "Hindi"),
    ("hu", "Hungarian"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ms", "Malay"),
    ("no", "Norwegian"),
    ("pl", "Polish"),
    ("pt-br", "Portuguese (Brazil)"),
    ("pt", "Portuguese (Portugal)"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sk", "Slovak"),
    ("es", "Spanish"),
    ("sv", "Swedish"),
    ("ta", "Tamil"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
]

llm_list = [
    # OpenAI
    ("gpt-3.5-turbo", "GPT 3.5 Turbo"),
    ("gpt-4o-mini", "GPT 4o Mini"),
    ("gpt-4o", "GPT 4o"),
    ("gpt-4-turbo", "GPT 4 Turbo"),
    ("gpt-4", "GPT 4"),
    ("gpt-4.1", "GPT 4.1"),
    ("gpt-4.1-mini", "GPT 4.1 Mini"),
    ("gpt-4.1-nano", "GPT 4.1 Nano"),
    ("gpt-5", "GPT 5"),
    ("gpt-5-mini", "GPT 5 Mini"),
    ("gpt-5-nano", "GPT 5 Nano"),
    ("gpt-5.1", "GPT 5.1"),
    ("gpt-5.2", "GPT 5.2"),
    # Gemini (Google)
    ("gemini-1.0-pro", "Gemini 1.0 Pro"),
    ("gemini-1.5-pro", "Gemini 1.5 Pro"),
    ("gemini-1.5-flash", "Gemini 1.5 Flash"),
    ("gemini-2.0-flash-001", "Gemini 2.0 Flash 001"),
    ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite"),
    ("gemini-3-pro-preview", "Gemini 3 Pro Preview"),
    ("gemini-3-flash-preview", "Gemini 3 Flash Preview"),
    # Anthropic (Claude)
    ("claude-3-5-sonnet", "Claude 3.5 Sonnet"),
    ("claude-3-5-sonnet-v1", "Claude 3.5 Sonnet v1"),
    ("claude-3-7-sonnet", "Claude 3.7 Sonnet"),
    ("claude-3-haiku", "Claude 3 Haiku"),
    ("claude-sonnet-4.5", "Claude Sonnet 4.5"),
    ("claude-sonnet-4", "Claude Sonnet 4"),
    ("claude-haiku-4.5", "Claude Haiku 4.5"),
    # ElevenLabs hosted (open-source)
    ("glm-4.5-air", "GLM 4.5 Air"),
    ("qwen3-30b-a3b", "Qwen3 30B A3B"),
    # Другие (если поддерживаются)
    ("grok-beta", "Grok Beta"),
]


class ElevenlabsAgent(models.Model):
    _name = "connect.elevenlabs_agent"
    _description = "Elevenlabs Agent"

    name = fields.Char(required=True)
    voice = fields.Many2one("connect.elevenlabs_voice", required=True)
    first_message = fields.Char(
        default="Hi there! How could I help you today?", required=True, translate=True
    )
    prompt = fields.Text(required=True)
    prompt_version_ids = fields.One2many(
        "connect.elevenlabs_agent_prompt", "agent", string="Prompt Versions"
    )
    active_prompt_version = fields.Many2one(
        "connect.elevenlabs_agent_prompt",
        string="Prompt Version",
        domain="[('agent', '=', id)]",
    )
    language = fields.Selection(selection=language_list, default="en", required=True)
    additional_languages = fields.Many2many(
        "res.lang", domain=[("active", "=", True)], required=True
    )
    tools = fields.Many2many("connect.elevenlabs_agent_tool")
    temperature = fields.Float(required=True, default=0.0)
    max_tokens = fields.Integer(
        required=True,
        default=-1,
        help="If greater than 0, maximum number of tokens the LLM can predict",
    )
    llm = fields.Selection(
        selection=llm_list, string="LLM", default="gpt-5.2", required=True
    )
    agent_uid = fields.Char(string="Agent ID")
    use_flash = fields.Boolean(default=True)
    output_audio_format = fields.Selection(
        [
            ("ulaw_8000", "ulaw 8000"),
            ("pcm_8000", "PCM 8000"),
            ("pcm_16000", "PCM 16000"),
            ("pcm_22050", "PCM 22050"),
            ("pcm_24000", "PCM 24000"),
            ("pcm_44100", "PCM 44100"),
            ("pcm_48000", "PCM 48000"),
        ],
        required=True,
        default="ulaw_8000",
    )
    user_input_audio_format = fields.Selection(
        [
            ("ulaw_8000", "ulaw 8000"),
            ("pcm_8000", "PCM 8000"),
            ("pcm_16000", "PCM 16000"),
            ("pcm_22050", "PCM 22050"),
            ("pcm_24000", "PCM 24000"),
            ("pcm_44100", "PCM 44100"),
            ("pcm_48000", "PCM 48000"),
        ],
        required=True,
        default="ulaw_8000",
    )
    model = fields.Selection(
        [
            ("eleven_turbo_v2", "Eleven Turbo v2"),
            ("eleven_turbo_v2_5", "Eleven Turbo v2.5"),
            ("eleven_flash_v2", "Eleven Flash v2"),
            ("eleven_flash_v2_5", "Eleven Flash v2.5"),
        ],
        required=True,
        default="eleven_flash_v2_5",
    )
    stability = fields.Float(default=0.5, required=True)
    speed = fields.Float(default=1.0, required=True)
    max_duration_seconds = fields.Integer(default=600, required=True)
    agent_concurrency_limit = fields.Integer(
        default=-1,
        required=True,
        help="The maximum number of concurrent conversations. -1 indicates that there is no maximum",
    )
    daily_limit = fields.Integer(
        default=100000,
        required=True,
        help="The maximum number of conversations per day",
    )
    similarity_boost = fields.Float(default=0.8, required=True)
    turn_timeout = fields.Float(default=7.0, required=True)
    silence_end_call_timeout = fields.Integer(required=True, default=10)
    exten = fields.Many2one("connect.exten", ondelete="set null", readonly=True)
    exten_number = fields.Char(related="exten.number")
    template = fields.Many2one("connect.elevenlabs_agent_template", ondelete="set null")
    transfer_to_agent = fields.One2many("connect.elevenlabs_agent_transfer", "agent")
    has_transfer_tool = fields.Boolean(compute="_compute_has_transfer_tool")

    @api.depends("tools")
    def _compute_has_transfer_tool(self):
        transfer_tool = self.env.ref(
            "connect_elevenlabs.agent_tool_transfer_to_agent", raise_if_not_found=False
        )
        for rec in self:
            rec.has_transfer_tool = transfer_tool in rec.tools if transfer_tool else False

    @api.onchange("active_prompt_version")
    def _onchange_active_prompt_version(self):
        if self.active_prompt_version:
            self.prompt = self.active_prompt_version.prompt

    @api.onchange("template")
    def _onchange_template(self):
        if self.template:
            self.prompt = self.template.system_prompt

    @api.model_create_multi
    def create(self, vals_list):
        self.env['oduist.license'].check_license('connect_elevenlabs', silent=False)
        res = super().create(vals_list)
        if not self.env.context.get("skip_elevenlabs"):
            for rec in res:
                rec._sync_elevenlabs_agent()
        return res

    def write(self, vals):
        self.env['oduist.license'].check_license('connect_elevenlabs', silent=False)
        if vals.get('exten'):
            # Skip all syncing.
            return super().write(vals)
        res = super().write(vals)
        if "prompt" in vals and "active_prompt_version" not in vals:
            for rec in self:
                version_count = len(rec.prompt_version_ids)
                version = self.env["connect.elevenlabs_agent_prompt"].create(
                    {
                        "name": f"v{version_count + 1}",
                        "agent": rec.id,
                        "prompt": vals["prompt"],
                    }
                )
                rec.with_context(skip_elevenlabs=True).write(
                    {"active_prompt_version": version.id}
                )
        if not self.env.context.get("skip_elevenlabs"):
            self.update_elevenlabs_agent()
            if not self.knowledge_base_note and self.knowledge_base_id:
                self.delete_elevenlabs_knowledge_base()
        return res

    def unlink(self):
        try:
            self.delete_elevenlabs_agent()
        except Exception as e:
            logger.exception("Error Delete Elevenlabs agent: %s", e)
        return super().unlink()

    @api.constrains("temperature")
    def _check_temperature(self):
        for rec in self:
            if rec.temperature and rec.temperature < 0 or rec.temperature > 1.0:
                raise ValidationError(
                    "Please enter a temperature value between 0.0 and 1.0."
                )

    @api.constrains("stability")
    def _check_stability(self):
        for rec in self:
            if rec.stability and rec.stability < 0 or rec.temperature > 1.0:
                raise ValidationError(
                    "Please enter a stability value between 0.0 and 1.0."
                )

    @api.constrains("speed")
    def _check_speed(self):
        for rec in self:
            if rec.speed and rec.speed < 0.7 or rec.speed > 1.2:
                raise ValidationError("Please enter a speed value between 0.7 and 1.2.")

    @api.constrains("speed")
    def _check_similarity_boost(self):
        for rec in self:
            if (
                rec.similarity_boost
                and rec.similarity_boost < 0
                or rec.similarity_boost > 1
            ):
                raise ValidationError(
                    "Please enter a similarity boost value between 0 and 1."
                )

    def _sync_elevenlabs_agent(self):
        """Create ElevenLabs agent and sync it with Odoo."""
        self.ensure_one()
        agent = self.create_elevenlabs_agent()
        self.with_context(skip_elevenlabs=True).write({"agent_uid": agent.agent_id})
        self.update_elevenlabs_agent()

    def create_extension(self):
        self.ensure_one()
        return self.env["connect.exten"].create_extension(self, "elevenlabs_agent")

    def render(self, request, params={}):
        self.ensure_one()
        if not self.env["oduist.license"].check_license('connect_elevenlabs'):
            return "<Response><Pause length='1'/><Say>This is Oduist Connect. Your trial period is over. Please buy a license to continue.</Say><Pause length='1'/></Response>"
        channel_sid = request.get("CallSid")
        call_id = (
            self.env["connect.channel"]
            .search([("sid", "=", channel_sid)], limit=1)
            .call.id
        )
        elevenlabs_agent_url = (
            self.env["connect.settings"]
            .sudo()
            .get_param("elevenlabs_agent_url")
            .replace("https://", "wss://")
        )
        agent_uid = self.agent_uid
        connect = Connect()
        connect.stream(
            url=f"{elevenlabs_agent_url}/twilio/stream/{agent_uid}/{call_id}/{channel_sid}",
        )
        response = VoiceResponse()
        response.append(connect)
        debug(self, pretty_xml(response))
        return response

    @api.model
    def transfer(self, channel_sid=None, exten=None):
        logger.info(f"Transfer request: exten={exten}, channel_sid={channel_sid}")
        if not channel_sid or not exten:
            return "Not all parameters passed. You must provide channel_sid and exten (only digits)"
        if isinstance(exten, str) and not exten.isalnum():
            return "Wrong extension format. Only digits, e.g. 101"
        self = self.sudo()
        client = self.env["connect.settings"].get_client()
        channel = self.env["connect.channel"].search([("sid", "=", channel_sid)])
        exten_rec = self.env["connect.exten"].search(
            [("number", "=", str(exten).strip())]
        )
        if not exten_rec:
            # Get all published extensions
            published_extens = self.env['connect.exten'].search([('is_published', '=', True)])
            if published_extens:
                available = ", ".join(
                    ['<{}> "{}"'.format(k.number, k.dst.name if k.dst else '') for k in published_extens]
                )
                if len(published_extens) == 1:
                    exten_rec = published_extens[0]
                    logger.info(
                        "Extension %s not found, falling back to single published extension %s",
                        exten,
                        exten_rec.number,
                    )
                else:
                    return f"Extension {exten} not found. Available extensions: {available}. Please try again with a correct number."
            else:
                return "There is no public extension to connect the call. Cannot transfer"
        exten = exten_rec
        twiml = exten.render(
            {
                "Caller": channel.caller,
                "Called": channel.called,
                "CallSid": channel.sid,
            }
        )
        debug(self, "Transfer to: {}".format(pretty_xml(twiml)))
        client.calls(channel_sid).update(twiml=twiml)
        return "Transfer Successful"

    def create_elevenlabs_agent(self):
        client = self.env["connect.settings"].get_elevenlabs_client()
        try:
            conversation_config = self._build_conversational_config()
            return client.conversational_ai.agents.create(
                name=self.name,
                conversation_config=conversation_config,
                platform_settings=self._build_platform_settings(),
            )
        except Exception as e:
            logger.exception("Error creating ElevenLabs agent: %s", e)
            raise

    def update_elevenlabs_agent(self):
        client = self.env["connect.settings"].get_elevenlabs_client()
        try:
            conversation_config = self._build_conversational_config()
            client.conversational_ai.agents.update(
                agent_id=self.agent_uid,
                name=self.name,
                conversation_config=conversation_config,
                platform_settings=self._build_platform_settings(),
            )
        except ApiError as e:
            if e.status_code == 404:
                logger.exception("Agent doesn't exist! Create.")
                self._sync_elevenlabs_agent()
                self.update_elevenlabs_agent()
            else:
                logger.exception("Error updating ElevenLabs agent: %s", e)
                raise
        except Exception as e:
            logger.exception("Error updating ElevenLabs agent: %s", e)
            raise

    def delete_elevenlabs_agent(self):
        client = self.env["connect.settings"].get_elevenlabs_client()
        try:
            client.conversational_ai.agents.delete(agent_id=self.agent_uid)
        except Exception as e:
            logger.exception("Error deleting ElevenLabs agent: %s", e)
            raise

    def _build_conversational_config(self) -> ConversationalConfig:
        """Build proper ConversationalConfig object using new API types"""

        def get_model():
            version = "2_5"
            if self.language == "en":
                version = "2"
            return (
                f"eleven_flash_v{version}"
                if self.use_flash
                else f"eleven_turbo_v{version}"
            )

        # Build agent config - using dict due to complex nested structure
        dynamic_variable_placeholders = {}
        for tool in self.tools:
            dynamic_variable_placeholders.update(
                dict(
                    [
                        (param.name, f"test_{param.name}")
                        for param in tool.params
                        if param.value_type == "dynamic_variable"
                    ]
                )
            )

        agent_dict = {
            "first_message": self.first_message,
            "language": self.language,
        }

        if dynamic_variable_placeholders:
            agent_dict["dynamic_variables"] = dynamic_variable_placeholders

        agent_dict["prompt"] = self._compute_prompt_config()

        # Build ASR config
        asr_dict = {"user_input_audio_format": self.user_input_audio_format}

        # Build TTS config
        tts_dict = {
            "agent_output_audio_format": self.output_audio_format,
            "similarity_boost": self.similarity_boost,
            "speed": self.speed,
            "stability": self.stability,
            "voice_id": self.voice.voice_id,
            "model_id": get_model(),
        }

        # Build conversation config
        conversation_dict = {"max_duration_seconds": self.max_duration_seconds}

        # Build language presets
        language_presets = {}
        first_message_translations = self.get_field_translations("first_message")[0]
        for trans in first_message_translations:
            if trans["lang"] not in self.additional_languages.mapped("code"):
                logger.info(
                    "Not using language %s because not included in additional_languages.",
                    trans["lang"],
                )
                continue
            lang_code = trans["lang"].split("_")[0]
            language_presets[lang_code] = {
                "overrides": {
                    "agent": {
                        "first_message": trans["value"],
                    }
                }
            }

        # Return complete ConversationalConfig using dict structure
        config_dict = {
            "agent": agent_dict,
            "asr": asr_dict,
            "tts": tts_dict,
            "conversation": conversation_dict,
        }

        if language_presets:
            config_dict["language_presets"] = language_presets

        try:
            # Try standard validation first
            return ConversationalConfig(**config_dict)
        except Exception as e:
            logger.warning(
                f"Standard validation failed for ConversationalConfig: {e}. Using model_construct."
            )
            # Fallback to model_construct to bypass frozen validation
            return ConversationalConfig.model_construct(**config_dict)

    def _compute_built_in_tools(self):
        built_in_tools = {}
        for tool in self.tools:
            if tool.tool_type != "system":
                continue

            tool_config = {
                "type": "system",
                "name": tool.name,
                "description": tool.description or "",
                "params": {"system_tool_type": tool.name},
                "disable_interruptions": tool.disable_interruptions,
                "tool_error_handling_mode": "auto",
            }

            if tool.name == "transfer_to_agent":
                transfers = []
                for transfer in self.transfer_to_agent:
                    transfers.append(
                        {
                            "agent_id": transfer.transfer_to_agent.agent_uid,
                            "condition": transfer.condition,
                            "enable_transferred_agent_first_message": True,
                        }
                    )
                tool_config["params"]["transfers"] = transfers
            elif tool.name == "voicemail_detection":
                tool_config["params"]["voicemail_message"] = tool.voicemail_message or ""
            elif tool.name == "play_keypad_touch_tone":
                tool_config["params"]["use_out_of_band_dtmf"] = tool.use_out_of_band_dtmf

            built_in_tools[tool.name] = tool_config

        return built_in_tools

    def _compute_prompt_config(self):
        previous_topics = "\n\nLast conversation summary {{previous_topics}}."
        published_extensions = "\n\nCALL TRANSFER INFORMATION\n- Available extensions: {{available_extensions}}"
        agent_prompt = f"{self.prompt}{previous_topics}{published_extensions}"

        prompt_dict = {
            "prompt": agent_prompt,
            "llm": self.llm,
            "temperature": self.temperature,
            "tool_ids": self.compute_agent_tools(),
            "built_in_tools": self._compute_built_in_tools(),
        }

        if self.max_tokens > 0:
            prompt_dict["max_tokens"] = self.max_tokens
        return prompt_dict

    def _build_platform_settings(self) -> AgentPlatformSettingsRequestModel:
        """Build proper AgentPlatformSettingsRequestModel object using new API types"""
        return AgentPlatformSettingsRequestModel(
            overrides={
                "conversation_config_override": {
                    "agent": {
                        "language": True,
                    }
                },
            },
            call_limits={
                "agent_concurrency_limit": self.agent_concurrency_limit,
                "daily_limit": self.daily_limit,
            },
        )

    def compute_platform_settings(self):
        return {
            "overrides": {
                "conversation_config_override": {
                    "agent": {
                        "language": True,
                    }
                },
            },
            "call_limits": {
                "agent_concurrency_limit": self.agent_concurrency_limit,
                "daily_limit": self.daily_limit,
            },
        }

    def compute_language_presets(self):
        res = {}
        # TODO: Works on Odoo 18.0, backport to older version later.
        first_message_translations = self.get_field_translations("first_message")[0]
        for trans in first_message_translations:
            if trans["lang"] not in self.additional_languages.mapped("code"):
                logger.info(
                    "Not using language %s because not included in additional_languages.",
                    trans["lang"],
                )
                continue
            res[trans["lang"].split("_")[0]] = {
                "overrides": {
                    "agent": {
                        "first_message": trans["value"],
                    }
                }
            }
        return res

    def compute_agent_tools(self):
        agent_tools = []
        for tool in self.tools:
            if tool.tool_id:
                agent_tools.append(tool.tool_id)
        return agent_tools

    def print_config(self):
        client = self.env["connect.settings"].get_elevenlabs_client()
        agents = client.conversational_ai.agents.list().agents
        for agent in agents:
            agent = client.conversational_ai.agents.get(agent_id=agent.agent_id)
            logger.info(
                'Agent %s config:\n%s',
                agent.agent_id,
                json.dumps(str(agent.conversation_config.agent), indent=2),
            )
