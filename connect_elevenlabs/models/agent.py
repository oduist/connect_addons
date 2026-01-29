# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import models, fields, release, api, tools
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml
from odoo.exceptions import ValidationError
from elevenlabs.types import ConversationalConfig, AgentPlatformSettingsRequestModel
from elevenlabs.core.api_error import ApiError

# Supress a warning message.
import warnings
from pydantic.warnings import PydanticDeprecatedSince20

warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)

logger = logging.getLogger(__name__)

language_list = [
    ('ar', 'Arabic'),
    ('bg', 'Bulgarian'),
    ('zh', 'Chinese'),
    ('hr', 'Croatian'),
    ('cs', 'Czech'),
    ('da', 'Danish'),
    ('nl', 'Dutch'),
    ('en', 'English'),
    ('fi', 'Finnish'),
    ('fr', 'French'),
    ('de', 'German'),
    ('el', 'Greek'),
    ('hi', 'Hindi'),
    ('hu', 'Hungarian'),
    ('id', 'Indonesian'),
    ('it', 'Italian'),
    ('ja', 'Japanese'),
    ('ko', 'Korean'),
    ('ms', 'Malay'),
    ('no', 'Norwegian'),
    ('pl', 'Polish'),
    ('pt-br', 'Portuguese (Brazil)'),
    ('pt', 'Portuguese (Portugal)'),
    ('ro', 'Romanian'),
    ('ru', 'Russian'),
    ('sk', 'Slovak'),
    ('es', 'Spanish'),
    ('sv', 'Swedish'),
    ('ta', 'Tamil'),
    ('tr', 'Turkish'),
    ('uk', 'Ukrainian'),
    ('vi', 'Vietnamese'),
]

llm_list = [
    ('gpt-3.5-turbo', 'GPT 3.5 Turbo'),
    ('gpt-4o-mini', 'GPT 4o Mini'),
    ('gpt-4o', 'GPT 4o'),
    ('gpt-4', 'GPT 4'),
    ('gpt-4-turbo', 'GPT 4 Turbo'),
    ('gpt-4.1', 'GPT 4.1'),
    ('gpt-4.1-mini', 'GPT 4.1 Mini'),
    ('gpt-4.1-nano', 'GPT 4.1 Nano'),
    ('gemini-1.0-pro', 'Gemini 1.0 Pro'),
    ('gemini-1.5-pro', 'Gemini  1.5 Pro'),
    ('gemini-1.5-flash', 'Gemini 1.5 Flash'),
    ('gemini-2.0-flash-001', 'Gemini 2.0 Flash 001'),
    ('gemini-2.0-flash-lite', 'Gemini 2.0 Flash Lite'),
    ('gemini-2.5-flash', 'Gemini 2.0 Flash'),
    ('claude-3-5-sonnet', 'Claude 3.5 Sonnet'),
    ('claude-3-5-sonnet-v1', 'Claude 3.5 Sonnet v1'),
    ('claude-3-7-sonnet', 'Claude 3.7 Sonnet'),
    ('claude-3-haiku', 'Claude 2 Haiku'),
    ('grok-beta', 'Grok Beta'),
]

class ElevenlabsAgent(models.Model):
    _name = 'connect.elevenlabs_agent'
    _description = 'Elevenlabs Agent'

    name = fields.Char(required=True)
    voice = fields.Many2one('connect.elevenlabs_voice', required=True)
    first_message = fields.Char(default="Hi there! How could I help you today?", required=True, translate=True)
    prompt = fields.Text(required=True)
    language = fields.Selection(selection=language_list, default='en', required=True)
    additional_languages = fields.Many2many('res.lang', domain=[('active', '=', True)], required=True)
    tools = fields.Many2many('connect.elevenlabs_agent_tool')
    temperature = fields.Float(required=True, default=0.0)
    max_tokens = fields.Integer(
        required=True, default=-1, help='If greater than 0, maximum number of tokens the LLM can predict')
    llm = fields.Selection(selection=llm_list, string='LLM', default='gpt-4o', required=True)
    agent_uid = fields.Char(string="Agent ID")
    use_flash = fields.Boolean(default=True)
    output_audio_format = fields.Selection([
        ('ulaw_8000', 'ulaw 8000'),
        ('pcm_8000', 'PCM 8000'),
        ('pcm_16000', 'PCM 16000'),
        ('pcm_22050', 'PCM 22050'),
        ('pcm_24000', 'PCM 24000'),
        ('pcm_44100', 'PCM 44100'),
        ('pcm_48000', 'PCM 48000'),
    ], required=True, default='ulaw_8000')
    user_input_audio_format = fields.Selection([
        ('ulaw_8000', 'ulaw 8000'),
        ('pcm_8000', 'PCM 8000'),
        ('pcm_16000', 'PCM 16000'),
        ('pcm_22050', 'PCM 22050'),
        ('pcm_24000', 'PCM 24000'),
        ('pcm_44100', 'PCM 44100'),
        ('pcm_48000', 'PCM 48000'),
    ], required=True, default='ulaw_8000')
    model = fields.Selection([
        ('eleven_turbo_v2', 'Eleven Turbo v2'),
        ('eleven_turbo_v2_5', 'Eleven Turbo v2.5'),
        ('eleven_flash_v2', 'Eleven Flash v2'),
        ('eleven_flash_v2_5', 'Eleven Flash v2.5'),
        ],
        required=True, default='eleven_flash_v2_5')
    stability = fields.Float(default=0.5, required=True)
    speed = fields.Float(default=1.0, required=True)
    max_duration_seconds = fields.Integer(default=600, required=True)
    agent_concurrency_limit = fields.Integer(default=-1, required=True,
                                             help='The maximum number of concurrent conversations. -1 indicates that there is no maximum')
    daily_limit = fields.Integer(default=100000, required=True,
                                 help='The maximum number of conversations per day')
    similarity_boost = fields.Float(default=0.8, required=True)
    turn_timeout = fields.Float(default=7.0, required=True)
    silence_end_call_timeout = fields.Integer(required=True, default=10)
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number')
    template = fields.Many2one('connect.elevenlabs_agent_template', ondelete='set null')

    @api.onchange('template')
    def _onchange_template(self):
        if self.template:
            self.prompt = self.template.system_prompt

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        if not self.env.context.get('skip_elevenlabs'):
            for rec in res:
                rec._sync_elevenlabs_agent()
        return res

    def write(self, vals):
        if vals.get('exten'):
            # Skip all syncing.
            return super().write(vals)
        res = super().write(vals)
        if not self.env.context.get('skip_elevenlabs'):
            self.update_elevenlabs_agent()
        return res

    def unlink(self):
        try:
            self.delete_elevenlabs_agent()
        except Exception as e:
            logger.exception("Error Delete Elevenlabs agent: %s", e)
        return super().unlink()

    @api.constrains('temperature')
    def _check_temperature(self):
        for rec in self:
            if rec.temperature and rec.temperature < 0 or rec.temperature > 1.0:
                raise ValidationError('Please enter a temperature value between 0.0 and 1.0.')

    @api.constrains('stability')
    def _check_stability(self):
        for rec in self:
            if rec.stability and rec.stability < 0 or rec.temperature > 1.0:
                raise ValidationError('Please enter a stability value between 0.0 and 1.0.')

    @api.constrains('speed')
    def _check_speed(self):
        for rec in self:
            if rec.speed and rec.speed < 0.7 or rec.speed > 1.2:
                raise ValidationError('Please enter a speed value between 0.7 and 1.2.')

    @api.constrains('speed')
    def _check_similarity_boost(self):
        for rec in self:
            if rec.similarity_boost and rec.similarity_boost < 0 or rec.similarity_boost > 1:
                raise ValidationError('Please enter a similarity boost value between 0 and 1.')

    def _sync_elevenlabs_agent(self):
        """Create ElevenLabs agent and sync it with Odoo."""
        self.ensure_one()
        agent = self.create_elevenlabs_agent()
        self.with_context(skip_elevenlabs=True).write({'agent_uid': agent.agent_id})
        self.update_elevenlabs_agent()

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'elevenlabs_agent')

    def render(self, request, params={}):
        self.ensure_one()
        channel_sid = request.get("CallSid")
        call_id = self.env['connect.channel'].search([('sid', '=', channel_sid)], limit=1).call.id
        elevenlabs_agent_url = self.env['connect.settings'].sudo().get_param('elevenlabs_agent_url').replace('https://',
                                                                                                      'wss://')
        agent_uid = self.agent_uid
        connect = Connect()
        stream = connect.stream(
            url=f"{elevenlabs_agent_url}/twilio/stream/{agent_uid}/{call_id}/{channel_sid}",
        )
        #stream.parameter(name='skip_zrok_interstitial', value='1')
        response = VoiceResponse()
        response.append(connect)
        debug(self, pretty_xml(response))
        return response

    def transfer_test(self):
        client = self.env['connect.settings'].get_client()
        call = client.calls.create(
            to='+18109578170',
            from_='+18109578170',
            twiml="""<Response>
                <Pause length="1"/>
                <Connect>
                    <Stream url="wss://740e-2001-19f0-7400-1cfe-5400-4ff-fec7-4bbd.ngrok-free.app/twilio/stream/agent_01jvf4w2mretqvv55sxy0h50np/237/CA8ba5afd6763d6b6298500e6f96c66c14"/>
                </Connect>
            </Response> """
        )

    @api.model
    def transfer(self, params):
        channel_sid = params['channel_sid']
        exten = params['exten'] or params['default_exten']
        self = self.sudo()
        client = self.env['connect.settings'].get_client()
        channel = self.env['connect.channel'].search([('sid', '=', channel_sid)])
        exten = self.env['connect.exten'].search([('number', '=', exten)])
        if not exten:
            return 'Extension not found, please try again.'
        twiml = exten.render({
            'Caller': channel.caller,
            'Called': channel.called,
            'CallSid': channel.sid,
        })
        debug(self, 'Transfer to: {}'.format(pretty_xml(twiml)))
        client.calls(channel_sid).update(twiml=twiml)
        return True

    def create_elevenlabs_agent(self):
        client = self.env['connect.settings'].get_elevenlabs_client()
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
        client = self.env['connect.settings'].get_elevenlabs_client()
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
        client = self.env['connect.settings'].get_elevenlabs_client()
        try:
            client.conversational_ai.agents.delete(agent_id=self.agent_uid)
        except Exception as e:
            logger.exception("Error deleting ElevenLabs agent: %s", e)
            raise

    def _build_conversational_config(self) -> ConversationalConfig:
        """Build proper ConversationalConfig object using new API types"""

        def get_model():
            version = '2_5'
            if self.language == 'en':
                version = '2'
            return f'eleven_flash_v{version}' if self.use_flash else f'eleven_turbo_v{version}'

        # Build agent config - using dict due to complex nested structure
        dynamic_variable_placeholders = {}
        for tool in self.tools:
            dynamic_variable_placeholders.update(
                dict([(param.name, f'test_{param.name}') for param in tool.params if
                      param.value_type == 'dynamic_variable']))

        agent_dict = {
            'first_message': self.first_message,
            'language': self.language,
        }

        if dynamic_variable_placeholders:
            agent_dict['dynamic_variables'] = dynamic_variable_placeholders

        agent_dict['prompt'] = self._compute_prompt_config()

        # Build ASR config
        asr_dict = {
            'user_input_audio_format': self.user_input_audio_format
        }

        # Build TTS config
        tts_dict = {
            'agent_output_audio_format': self.output_audio_format,
            'similarity_boost': self.similarity_boost,
            'speed': self.speed,
            'stability': self.stability,
            'voice_id': self.voice.voice_id,
            'model_id': get_model(),
        }

        # Build conversation config
        conversation_dict = {
            'max_duration_seconds': self.max_duration_seconds
        }

        # Build language presets
        language_presets = {}
        first_message_translations = self.get_field_translations('first_message')[0]
        for trans in first_message_translations:
            if trans['lang'] not in self.additional_languages.mapped('code'):
                logger.info('Not using language %s because not included in additional_languages.',
                            trans['lang'])
                continue
            lang_code = trans['lang'].split('_')[0]
            language_presets[lang_code] = {
                'overrides': {
                    'agent': {
                        'first_message': trans['value'],
                    }
                }
            }

        # Return complete ConversationalConfig using dict structure
        config_dict = {
            'agent': agent_dict,
            'asr': asr_dict,
            'tts': tts_dict,
            'conversation': conversation_dict,
        }

        if language_presets:
            config_dict['language_presets'] = language_presets

        try:
            # Try standard validation first
            return ConversationalConfig(**config_dict)
        except Exception as e:
            logger.warning(f"Standard validation failed for ConversationalConfig: {e}. Using model_construct.")
            # Fallback to model_construct to bypass frozen validation
            return ConversationalConfig.model_construct(**config_dict)

    def _compute_built_in_tools(self):
        built_in_tools = {}
        for tool in self.tools:
            if tool.tool_type == 'system':
                built_in_tools.update({
                    tool.name: {
                        "type": "system",
                        "name": tool.name,
                        "description": "",
                        "params": {
                            "system_tool_type": tool.name
                        },
                        "disable_interruptions": False
                    },
                })

        return built_in_tools

    def _compute_prompt_config(self):
        previous_topics = '\nLast conversation summary {{previous_topics}}.'
        agent_prompt = f'{self.prompt}{previous_topics}'

        prompt_dict = {
            'prompt': agent_prompt,
            'llm': self.llm,
            'temperature': self.temperature,
            'tool_ids': self.compute_agent_tools(),
            'built_in_tools': self._compute_built_in_tools(),
        }

        if self.max_tokens > 0:
            prompt_dict['max_tokens'] = self.max_tokens
        return prompt_dict

    def _build_platform_settings(self) -> AgentPlatformSettingsRequestModel:
        """Build proper AgentPlatformSettingsRequestModel object using new API types"""
        return AgentPlatformSettingsRequestModel(
            overrides={
                'conversation_config_override': {
                    'agent': {
                        'language': True,
                    }
                },
            },
            call_limits={
                'agent_concurrency_limit': self.agent_concurrency_limit,
                'daily_limit': self.daily_limit,
            }
        )

    def compute_platform_settings(self):
        return {
            'overrides': {
                'conversation_config_override': {
                    'agent': {
                        'language': True,
                    }
                },
            },
            "call_limits": {
                "agent_concurrency_limit": self.agent_concurrency_limit,
                "daily_limit": self.daily_limit,
            }
        }

    def compute_language_presets(self):
        res = {}
        # TODO: Works on Odoo 18.0, backport to older version later.
        first_message_translations = self.get_field_translations('first_message')[0]
        for trans in first_message_translations:
            if trans['lang'] not in self.additional_languages.mapped('code'):
                logger.info('Not using language %s because not included in additional_languages.',
                            trans['lang'])
                continue
            res[trans['lang'].split('_')[0]] = {
                "overrides": {
                    "agent": {
                        "first_message": trans['value'],
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
        client = self.env['connect.settings'].get_elevenlabs_client()
        agents = client.conversational_ai.agents.list().agents
        for agent in agents:
            agent = client.conversational_ai.agents.get(agent_id=agent.agent_id)
            print(json.dumps(str(agent.conversation_config.agent), indent=2))
            # tools = agent.conversation_config.agent.prompt.tools
            # for tool in tools:
            #    print(tool)
