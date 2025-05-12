# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml
from odoo.exceptions import ValidationError
from elevenlabs import ElevenLabs, ConversationConfig

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
    type = fields.Selection(
        [('string', 'String'), ('boolean', 'Boolean'), ('integer', 'Integer')], default='string', required=True)
    required = fields.Boolean()
    value_type = fields.Selection(
        [('dynamic_variable', 'Dynamic Variable'), ('constant', 'Constant Variable')],
        default='dynamic_variable', required=True)
    constant_value = fields.Char()
    dynamic_variable = fields.Char()
    tool = fields.Many2one('connect.elevenlabs_agent_tool')


class ElevenlabsAgentTool(models.Model):
    _name = 'connect.elevenlabs_agent_tool'
    _description = 'Elevenlabs Agent Tool'

    name = fields.Char(required=True)
    tool_id = fields.Char(readonly=True)
    description = fields.Char(required=True)
    type = fields.Selection(
        [('client', 'Client'), ('webhook', 'Webhook'), ('system', 'System')], default='webhook', required=True)
    url = fields.Char()
    method = fields.Selection([('POST', 'POST'), ('GET', 'GET')], default='POST')
    props = fields.One2many('connect.agent_tool_props', 'tool')
    props_description = fields.Char()
    param = fields.Selection([('end_call', 'end_call')])

    @api.model_create_multi
    def create(self, vals_list):
        for val in vals_list:
            val.update({'name': val.get('param')})
        return super().create(vals_list)

    @api.onchange('param')
    def on_set_param(self):
        self.name = self.param


class ElevenlabsAgent(models.Model):
    _name = 'connect.elevenlabs_agent'
    _description = 'Elevenlabs Agent'

    name = fields.Char(required=True)
    first_message = fields.Char(default="Hi there! How could I help you today?", required=True)
    prompt = fields.Text(required=True, default="You are Harper, a vibrant and personable sales consultant with "
                                                "a passion for Conversational AI systems. ")
    language = fields.Selection(selection=language_list, default='en', required=True)
    tools = fields.Many2many('connect.elevenlabs_agent_tool')
    llm = fields.Selection(selection=llm_list, default='gpt-4o', required=True)
    agent_id = fields.Char(string="Agent ID", readonly=True)
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
                    'prompt': self.prompt,
                    'llm': self.llm,
                    'tools': self.compute_agent_tool() if self.tools and not skip_tools else []
                }
            }
        }
        from pprint import pprint
        pprint(config)
        return config

    def compute_agent_tool(self):
        tools = []
        for tool in self.tools:
            tools.append({
                'name': tool.name,
                'description': tool.description,
                'type': tool.type,
                'api_schema': {
                    'method': tool.method,
                    'url': tool.url,
                    'request_body_schema': {
                        "description": tool.props_description,
                        'properties': {
                            prop.name: {
                                'type': prop.type,
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
