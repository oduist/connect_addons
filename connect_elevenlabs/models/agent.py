# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import models, fields, release, api, tools
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml
from odoo.exceptions import ValidationError
from elevenlabs import ConversationConfig

# Supress a warning message.
import warnings
from pydantic.warnings import PydanticDeprecatedSince20

warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)

logger = logging.getLogger(__name__)

default_prompt = """
You are Harper, a vibrant and personable sales consultant with a passion for Conversational AI systems.
"""

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
    prompt = fields.Html(required=True, default=default_prompt)
    language = fields.Selection(selection=language_list, default='en', required=True)
    additional_languages = fields.Many2many('res.lang', domain=[('active', '=', True)], required=True)
    tools = fields.Many2many('connect.elevenlabs_agent_tool')
    temperature = fields.Float(required=True, default=0.0)
    max_tokens = fields.Integer(
        required=True, default=-1, help='If greater than 0, maximum number of tokens the LLM can predict')
    llm = fields.Selection(selection=llm_list, string='LLM', default='gpt-4o', required=True)
    agent_uid = fields.Char(string="Agent ID")
    knowledge_base_name = fields.Char()
    knowledge_base_note = fields.Text()
    knowledge_base_id = fields.Char()
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

    @api.model_create_multi
    def create(self, vals_list):
        self.env['connect.license'].check_license('connect_elevenlabs', silent=False)
        res = super().create(vals_list)
        if not self.env.context.get('skip_elevenlabs'):
            for rec in res:
                rec.create_elevenlabs_knowledge_base()
                agent = rec.create_elevenlabs_agent()
                rec.with_context(skip_elevenlabs=True).write({'agent_uid': agent.agent_id})
                rec.update_elevenlabs_agent()
        return res

    def write(self, vals):
        self.env['connect.license'].check_license('connect_elevenlabs', silent=False)
        if vals.get('exten'):
            # Skip all syncing.
            return super().write(vals)
        res = super().write(vals)
        if not self.env.context.get('skip_elevenlabs'):
            if 'knowledge_base_note' or 'knowledge_base_name' in vals.keys() and self.knowledge_base_note:
                self.update_elevenlabs_knowledge_base()
            self.update_elevenlabs_agent()
            if not self.knowledge_base_note and self.knowledge_base_id:
                self.delete_elevenlabs_knowledge_base()
        return res

    def unlink(self):
        try:
            self.delete_elevenlabs_agent()
            self.delete_elevenlabs_knowledge_base()
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

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'elevenlabs_agent')

    def render(self, request, params={}):
        self.ensure_one()
        if not self.env["connect.license"].check_license('connect_elevenlabs'):
            return "<Response><Pause length='1'/><Say>This is Oduist Connect. Your trial period is over. Please buy a license to continue.</Say><Pause length='1'/></Response>"
        channel_sid = request.get("CallSid")
        call_id = self.env['connect.channel'].search([('sid', '=', channel_sid)], limit=1).call.id
        elevenlabs_agent_url = self.env['connect.settings'].sudo().get_param('elevenlabs_agent_url').replace('https://',
                                                                                                      'wss://')
        agent_uid = self.agent_uid
        connect = Connect()
        connect.stream(
            url=f"{elevenlabs_agent_url}/twilio/stream/{agent_uid}/{call_id}/{channel_sid}",
        )
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

    def create_elevenlabs_knowledge_base(self):
        if self.knowledge_base_note:
            client = self.env['connect.settings'].get_elevenlabs_client()
            knowledge_base = client.conversational_ai.create_knowledge_base_text_document(
                text=self.knowledge_base_note, name=self.knowledge_base_name)
            if knowledge_base:
                self.with_context(skip_elevenlabs=True).write({'knowledge_base_id': knowledge_base.id})
            return knowledge_base.id
        return None

    def update_elevenlabs_knowledge_base(self):
        if self.knowledge_base_note and self.knowledge_base_id:
            key = self.env['connect.settings'].sudo().get_param('elevenlabs_api_key')
            url = f"https://api.elevenlabs.io/v1/convai/knowledge-base/{self.knowledge_base_id}"
            headers = {"Content-Type": "application/json", "xi-api-key": key}
            payload = {'name': self.knowledge_base_name, 'text': self.knowledge_base_note}
            response = requests.patch(url, headers=headers, json=payload)
        elif self.knowledge_base_note and not self.knowledge_base_id:
            self.create_elevenlabs_knowledge_base()
        return True

    def delete_elevenlabs_knowledge_base(self):
        if self.knowledge_base_id:
            key = self.env['connect.settings'].sudo().get_param('elevenlabs_api_key')
            url = f"https://api.elevenlabs.io/v1/convai/knowledge-base/{self.knowledge_base_id}"
            headers = {"Content-Type": "application/json", "xi-api-key": key}
            response = requests.delete(url, headers=headers)
            # client = self.env['connect.settings'].get_elevenlabs_client()
            # client.conversational_ai.delete_knowledge_base_document(documentation_id=self.knowledge_base_id)
            self.with_context(skip_elevenlabs=True).write({'knowledge_base_id': None})

    def create_elevenlabs_agent(self):
        client = self.env['connect.settings'].get_elevenlabs_client()
        return client.conversational_ai.create_agent(
            name=self.name,
            conversation_config=ConversationConfig(),
            platform_settings=self.compute_platform_settings(),
        )

    def update_elevenlabs_agent(self):
        try:
            client = self.env['connect.settings'].get_elevenlabs_client()
            agent = client.conversational_ai.update_agent(
                agent_id=self.agent_uid,
                name=self.name,
                conversation_config=self.compute_agent_conversation_config(),
                platform_settings=self.compute_platform_settings(),
            )
        # We
        except Exception as e:
            if 'English Agents must use turbo or flash v2' in str(e):
                 error_msg = 'English only Agents must use v2 models!'
            else:
                error_msg = str(e)
            self.env['connect.settings'].connect_notify(error_msg, title='Agent Sync Error')

    def delete_elevenlabs_agent(self):
        client = self.env['connect.settings'].get_elevenlabs_client()
        client.conversational_ai.delete_agent(
            agent_id=self.agent_uid
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

    def compute_agent_conversation_config(self, skip_tools=False):
        dynamic_variable_placeholders = {}
        for tool in self.tools:
            dynamic_variable_placeholders.update(
                dict([(param.name, f'test_{param.name}') for param in tool.params if param.value_type == 'dynamic_variable']))
        previous_topics = '\nLast conversation summary {{previous_topics}}.'
        config = {
            'agent': {
                'first_message': self.first_message,
                'language': self.language,
                'dynamic_variables': dynamic_variable_placeholders,
                'prompt': {
                    'max_tokens': self.max_tokens,
                    'prompt': f'{tools.html2plaintext(self.prompt)}{previous_topics}',
                    'llm': self.llm,
                    'temperature': self.temperature,
                    'knowledge_base': [{
                        "type": "text",
                        "name": self.knowledge_base_name,
                        "id": self.knowledge_base_id,
                    }] if self.knowledge_base_note else [],
                    'tools': self.compute_agent_tools() if self.tools and not skip_tools else []
                }
            },
            "language_presets": self.compute_language_presets(),
            'asr': {
                'user_input_audio_format': self.user_input_audio_format
            },
            'conversation': {
                'max_duration_seconds': self.max_duration_seconds
            },
            'tts': {
                'agent_output_audio_format': self.output_audio_format,
                'similarity_boost': self.similarity_boost,
                'speed': self.speed,
                'stability': self.stability,
                'voice_id': self.voice.voice_id,
                'model_id': self.model,
            },
            'turn': {
                'turn_timeout': self.turn_timeout,
                'silence_end_call_timeout': self.silence_end_call_timeout,
                'mode': "turn"
            }
        }
        logger.info('Tools: {}'.format(json.dumps(config, indent=2)))
        return config

    def compute_agent_tools(self):
        tools = []
        for tool in self.tools:
            if not tool.is_enabled:
                continue
            dynamic_variables_placeholders = dict(
                [(param.name, f'test_{param.name}') for param in tool.params if param.value_type == 'dynamic_variable'])
            if tool.tool_type == 'client':
                tool_config = {
                    'type': tool.tool_type,
                    'description': tool.description,
                    'name': tool.name,
                    'dynamic_variables': dynamic_variables_placeholders,
                    'expects_response': tool.client_expects_response,
                    'parameters': {
                        "description": tool.body_params_description or '',
                        'required': [param.name for param in tool.params if param.required],
                        'properties': {
                            param.name: {
                                'type': param.data_type,
                                'description': param.description if param.value_type == 'description' else '',
                                "constant_value": param.constant_value if param.value_type == 'constant_value' else '',
                                "dynamic_variable": param.dynamic_variable if param.value_type == 'dynamic_variable' else '',
                            } for param in tool.params
                        }
                    },
                    'response_timeout_secs': tool.response_timeout_secs,
                }
                tools.append(tool_config)
            elif tool.tool_type == 'webhook':
                tool_config = {
                    'type': tool.tool_type,
                    'description': tool.description,
                    'name': tool.name,
                    'dynamic_variables': dynamic_variables_placeholders,
                    'response_timeout_secs': tool.response_timeout_secs,
                }
                tool_config.update({
                    'api_schema': {
                        'method': tool.method,
                        'url': tool.get_tool_url(),
                        'request_body_schema': {
                            "description": tool.body_params_description,
                            'required': [param.name for param in tool.params if param.required],
                            'properties': {
                                param.name: {
                                    'type': param.data_type,
                                    'description': param.description if param.value_type == 'description' else '',
                                    "constant_value": param.constant_value if param.value_type == 'constant_value' else '',
                                    "dynamic_variable": param.dynamic_variable if param.value_type == 'dynamic_variable' else '',
                                } for param in tool.params
                            }
                        },
                        'request_headers': {
                            'x-elevenlabs-agent-token': self.env['connect.settings'].get_param('elevenlabs_agent_token'),
                        }
                    },
                    'response_timeout_secs': tool.response_timeout_secs,
                })
                tools.append(tool_config)
            elif tool.tool_type == 'system':
                tool_config = {
                    'type': tool.tool_type,
                    'description': tool.description,
                    'name': tool.name,
                }
                tools.append(tool_config)
        return tools


    def print_config(self):
        client = self.env['connect.settings'].get_elevenlabs_client()
        agents = client.conversational_ai.get_agents().agents
        for agent in agents:
            agent = client.conversational_ai.get_agent(agent_id=agent.agent_uid)
            print(json.dumps(str(agent.conversation_config.agent), indent=2))
            #tools = agent.conversation_config.agent.prompt.tools
            #for tool in tools:
            #    print(tool)
