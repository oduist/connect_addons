# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml
from odoo.exceptions import ValidationError
from elevenlabs import ElevenLabs

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


class ElevenlabsAgentTool(models.Model):
    _name = 'connect.elevenlabs_agent_tool'
    _description = 'Elevenlabs Agent Tool'

    name = fields.Char(required=True)
    tool_id = fields.Char(readonly=True)
    description = fields.Char(required=True)
    dynamic_variables = fields.Text()
    type = fields.Selection([('client', 'Client'), ('webhook', 'Webhook')], default='webhook', required=True)
    agent = fields.Many2one('connect.elevenlabs_agent')


class ElevenlabsAgent(models.Model):
    _name = 'connect.elevenlabs_agent'
    _description = 'Elevenlabs Agent'

    name = fields.Char(required=True)
    voice = fields.Many2one('connect.elevenlabs_voice', required=True)
    first_message = fields.Char(default="Hi there! How could I help you today?", required=True)
    prompt = fields.Text(required=True, default="You are Harper, a vibrant and personable sales consultant with "
                                                "a passion for Conversational AI systems. ")
    language = fields.Selection(selection=language_list, default='en', required=True)
    temperature = fields.Float(required=True, default=0.0)
    max_tokens = fields.Integer(required=True, default=-1,
                                       help='If greater than 0, maximum number of tokens the LLM can predict')
    tools = fields.One2many('connect.elevenlabs_agent_tool', 'agent')
    llm = fields.Selection(selection=llm_list, default='gpt-4o', required=True)
    agent_id = fields.Char(string="Agent ID", readonly=True)
    knowledge_base_note = fields.Text()
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
        return res

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('skip_elevenlabs'):
            self.update_elevenlabs_agent()
        return res

    def unlink(self):
        self.delete_elevenlabs_agent()
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
        elevenlabs_agent_url = self.env['connect.settings'].get_param('elevenlabs_agent_url').replace('https://', 'wss://')
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

    def compute_agent_conversation_config(self):
        return {
            'agent': {
                'first_message': self.first_message,
                'language': self.language,
                'prompt': {
                    'prompt': self.prompt,
                    'llm': self.llm
                },
            }
        }

    def create_elevenlabs_agent(self):
        # try:
        client = self.env['connect.settings'].get_elevenlabs_client()
        return client.conversational_ai.create_agent(
            name=self.name,
            conversation_config=self.compute_agent_conversation_config()
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

    def update_agent_tool(self, agent):
        tools = []
        for tool in agent.conversation_config.agent.prompt.tools:
            print('TOOL', tool)
            tools.append({
                'name': tool.name,
                'description': tool.description,
                'type': tool.type,
                'dynamic_variables': '\n'.join(list(tool.dynamic_variables.dynamic_variable_placeholders.keys()))
            })

    def sync(self):
        client = self.env['connect.settings'].get_elevenlabs_client()
        agents = client.conversational_ai.get_agents().agents
        for agent in agents:
            agent = client.conversational_ai.get_agent(agent_id=agent.agent_id)
            agent_instance = self.search([('agent_id', '=', agent.agent_id)])
            if agent_instance:
                logger.info('Update agent: %s', agent.name)
                agent_instance.with_context(skip_elevenlabs=True).update(self.get_agent_data(agent))
            else:
                logger.info('Create agent: %s', agent.name)
                self.with_context(skip_elevenlabs=True).create([self.get_agent_data(agent)])
        self.env['connect.settings'].connect_notify('Sync complete.')
