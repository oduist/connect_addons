# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)

language_list = [
    ('en', 'English'),
    ('fr', 'French'),
    ('de', 'German'),
    ('es', 'Spanish'),
    ('pt', 'Portuguese'),
    ('ru', 'Russian'),
    ('zh', 'Chinese'),
    ('hi', 'Hindi'),
]

llm_list = [
    ('gpt-3.5-turbo', 'GPT 3.5 Turbo'),
    ('gpt-4o-mini', 'GPT 4o Mini'),
    ('gpt-4o', 'GPT 4o'),
    ('gpt-4-turbo', 'GPT 4 Turbo'),
    ('gemini-2.0-flash-lite', 'Gemini 2.0 Flash Lite'),
    ('gemini-2.5-flash', 'Gemini 2.0 Flash'),
    ('claude-3-5-sonnet', 'Claude 3.5 Sonnet'),
    ('claude-3-7-sonnet', 'Claude 3.7 Sonnet'),
    ('claude-3-haiku', 'Claude 2 Haiku'),
    ('grok-beta', 'Grok Beta'),
]


class ElevenlabsAgentToolProps(models.Model):
    _name = 'connect.agent_tool_props'
    _description = 'Elevenlabs Agent Tool'

    name = fields.Char()
    data_type = fields.Selection(
        [('string', 'String'), ('boolean', 'Boolean'), ('integer', 'Integer')], default='string', required=True)
    required = fields.Boolean()
    value_type = fields.Selection(
        [('dynamic_variable', 'Dynamic Variable'),
         ('constant', 'Constant Variable'),
         ('llm', 'LLM Prompt'),
        ],
        default='llm', required=True)
    constant_value = fields.Char()
    dynamic_variable = fields.Char()
    description = fields.Char()
    tool = fields.Many2one('connect.elevenlabs_agent_tool')


class ElevenlabsAgentTool(models.Model):
    _name = 'connect.elevenlabs_agent_tool'
    _description = 'Elevenlabs Agent Tool'

    name = fields.Char(required=True)
    tool_id = fields.Char(readonly=True)
    description = fields.Char(required=True)
    tool_type = fields.Selection(
        [('client', 'Client'), ('webhook', 'Webhook'), ('system', 'System')], default='webhook', required=True)
    url = fields.Char()
    method = fields.Selection([('POST', 'POST'), ('GET', 'GET')], default='POST')
    props = fields.One2many('connect.agent_tool_props', 'tool')
    props_description = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)


class ElevenlabsAgent(models.Model):
    _name = 'connect.elevenlabs_agent'
    _description = 'Elevenlabs Agent'

    name = fields.Char(required=True)
    voice = fields.Many2one('connect.elevenlabs_voice', required=True)
    first_message = fields.Char(default="Hi there! How could I help you today?", required=True)
    prompt = fields.Html(required=True, default="You are Harper, a vibrant and personable sales consultant with "
                                                "a passion for Conversational AI systems. ")
    language = fields.Selection(selection=language_list, default='en', required=True)
    tools = fields.Many2many('connect.elevenlabs_agent_tool')
    temperature = fields.Float(required=True, default=0.0)
    max_tokens = fields.Integer(
        required=True, default=-1, help='If greater than 0, maximum number of tokens the LLM can predict')
    llm = fields.Selection(selection=llm_list, default='gpt-4o', required=True)
    agent_id = fields.Char(string="Agent ID", readonly=True)
    knowledge_base_note = fields.Text()
    knowledge_base_id = fields.Char()
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
    stability = fields.Float(default=0.5, required=True)
    speed = fields.Float(default=1.0, required=True)
    max_duration_seconds = fields.Integer(default=600, required=True)
    agent_concurrency_limit = fields.Integer(default=-1, required=True,
                                             help='The maximum number of concurrent conversations. -1 indicates that there is no maximum')
    daily_limit = fields.Integer(default=100000, required=True,
                                 help='The maximum number of conversations per day')
    similarity_boost = fields.Float(default=0.8, required=True)
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number')

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        if not self.env.context.get('skip_elevenlabs'):
            for rec in res:
                agent = rec.create_elevenlabs_agent()
                rec.agent_id = agent.agent_id
                rec.update_elevenlabs_agent()
        return res

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_elevenlabs'):
            self.update_elevenlabs_agent()
        return res

    def unlink(self):
        try:
            self.delete_elevenlabs_agent()
        except Exception as e:
            logger.exception("Error Delete Elevenlabs agent: ", e)
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
        channel_sid = request.get("CallSid")
        call_id = self.env['connect.channel'].search([('sid', '=', channel_sid)], limit=1).call.id
        elevenlabs_agent_url = self.env['connect.settings'].get_param('elevenlabs_agent_url').replace('https://',
                                                                                                      'wss://')
        agent_id = self.agent_id
        connect = Connect()
        connect.stream(url=f"{elevenlabs_agent_url}/twilio/stream/{agent_id}/{call_id}/{channel_sid}")
        response = VoiceResponse()
        response.append(connect)
        debug(self, pretty_xml(response))
        return response

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
        # try:
        client = self.env['connect.settings'].get_elevenlabs_client()
        return client.conversational_ai.create_agent(
            name=self.name,
            conversation_config=self.compute_agent_conversation_config(skip_tools=True)
        )
        # except Exception as e:
        #     logger.exception("Error create Elevenlabs agent: ", e)

    def update_elevenlabs_agent(self):
        # try:
        client = self.env['connect.settings'].get_elevenlabs_client()
        agent = client.conversational_ai.update_agent(
            agent_id=self.agent_id,
            name=self.name,
            conversation_config=self.compute_agent_conversation_config()
        )
        # except Exception as e:
        # logger.exception("Error update Elevenlabs agent: ", e)

    def delete_elevenlabs_agent(self):
        # try:
        client = self.env['connect.settings'].get_elevenlabs_client()
        client.conversational_ai.delete_agent(
            agent_id=self.agent_id
        )
        # except Exception as e:
        #     logger.exception("Error update Elevenlabs agent: ", e)

    def compute_agent_conversation_config(self, skip_tools=False):
        config = {
            'agent': {
                'first_message': self.first_message,
                'language': self.language,
                'prompt': {
                    'max_tokens': self.max_tokens,
                    'prompt': self.prompt,
                    'llm': self.llm,
                    'temperature': self.temperature,
                    'tools': self.compute_agent_tool() if self.tools and not skip_tools else []
                }
            },
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
                'voice_id': self.voice.voice_id
            },
            'platform_settings': {
                "call_limits": {
                    "agent_concurrency_limit": self.agent_concurrency_limit,
                    "daily_limit": self.daily_limit,
                }
            }
        }
        return config

    def compute_agent_tool(self):
        tools = []
        for tool in self.tools:
            tools.append({
                'name': tool.name,
                'description': tool.description,
                'type': tool.tool_type,
                'api_schema': {
                    'method': tool.method,
                    'url': tool.url,
                    'request_body_schema': {
                        "description": tool.props_description,
                        'properties': {
                            prop.name: {
                                'type': prop.data_type,
                                'value_type': prop.value_type,
                                "constant_value": prop.constant_value if prop.value_type == 'constant' else '',
                                "dynamic_variable": prop.dynamic_variable if prop.value_type == 'dynamic_variable' else '',
                            } for prop in tool.props
                        }
                    }
                },
                'dynamic_variables': {tool.name: f'test_{tool.name}' if tool.type == 'dynamic_variable' else {}},
            })
        return tools

    @staticmethod
    def get_agent_data(agent):
        return {
            'agent_id': agent.agent_id,
            'name': agent.name,
            'first_message': agent.conversation_config.agent.first_message,
            'language': agent.conversation_config.agent.language,
            'prompt': agent.conversation_config.agent.prompt.prompt,
            'llm': agent.conversation_config.agent.prompt.llm,
        }

    def sync(self):
        client = self.env['connect.settings'].get_elevenlabs_client()
        agents = client.conversational_ai.get_agents().agents
        for agent in agents:
            agent = client.conversational_ai.get_agent(agent_id=agent.agent_id)
            tools = agent.conversation_config.agent.prompt.tools
            for tool in tools:
                print(tool)
            break
            agent_instance = self.search([('agent_id', '=', agent.agent_id)])
            if agent_instance:
                logger.info('Update agent: %s', agent.name)
                agent_instance.with_context(skip_elevenlabs=True).update(self.get_agent_data(agent))
            else:
                logger.info('Create agent: %s', agent.name)
                self.with_context(skip_elevenlabs=True).create([self.get_agent_data(agent)])
        self.env['connect.settings'].connect_notify('Sync complete.')
