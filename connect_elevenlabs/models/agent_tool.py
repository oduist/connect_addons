# -*- coding: utf-8 -*-
import json
import re
import urllib.parse
import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from elevenlabs import ToolRequestModel, ToolRequestModelToolConfig_Client, ToolRequestModelToolConfig_Webhook

logger = logging.getLogger(__name__)


class ElevenlabsAgentTool(models.Model):
    _name = 'connect.elevenlabs_agent_tool'
    _description = 'Elevenlabs Agent Tool'
    _order = 'name'

    name = fields.Char(required=True)
    tool_id = fields.Char()
    description = fields.Text(required=True)
    tool_type = fields.Selection(
        [('client', 'Client'), ('webhook', 'Webhook'), ('system', 'System')], default='webhook', required=True)
    path = fields.Char()
    url = fields.Char(string='URL')
    method = fields.Selection(
        [('GET', 'GET'), ('POST', 'POST'), ('PATCH', 'PATCH'), ('PUT', 'PUT'), ('DELETE', 'DELETE')],
        default='POST', required=True)
    params = fields.One2many('connect.agent_tool_params', 'tool', string='Parameters')
    body_params_description = fields.Char(string='Parameters Description')
    response_timeout_secs = fields.Integer(required=True, default=20, string='Response Timeout')
    param_type = fields.Selection([
        # ('query', 'Query'),
        # ('path', 'Path'),
        ('body', 'Body')  # Only JSON is implemented for now.
    ], default='body', required=True)
    client_expects_response = fields.Boolean(string='Expects Response',
                                             help='If true, calling this tool should block the conversation until the client responds with some response which is passed to the llm. If false then we will continue the conversation without waiting for the client to respond, this is useful to show content to a user but not block the conversation')

    _sql_constraints = [
        ('name_unique', 'UNIQUE(name)', 'This name is already used!')
    ]

    def get_tool_url(self):
        api_url = self.env['ir.config_parameter'].sudo().get_param('connect.api_url')
        if self.path:
            # We return Odoo URL for internal tools.
            return urllib.parse.urljoin(api_url, self.path)
        elif self.url:
            # External URLs.
            return self.url
        else:
            # Constraint to set path or URL!
            raise ValidationError('Tool {} path or URL is not set!'.format(self.name))

    @api.constrains('name')
    def _check_name(self):
        match = re.match("^[a-zA-Z0-9_-]{1,64}$", self.name)
        if not match:
            raise ValidationError(
                'Name must be less than 64 characters long and contain only alphanumerics, underscores and hyphens')

    @api.constrains('response_timeout_secs')
    def _check_response_timeout_secs(self):
        for rec in self:
            max_response_timeout_secs = 120 if rec.tool_type == 'webhook' else 30
            min_response_timeout_secs = 5 if rec.tool_type == 'webhook' else 1
            if rec.response_timeout_secs and rec.response_timeout_secs > max_response_timeout_secs or rec.response_timeout_secs < min_response_timeout_secs:
                raise ValidationError(
                    f'Please enter a response timeout value between {min_response_timeout_secs} and {max_response_timeout_secs}')

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        client = self.env['connect.settings'].get_elevenlabs_client()
        try:
            tool = client.conversational_ai.tools.create(
                request=ToolRequestModel(
                    tool_config=res.compute_agent_tools()
                )
            )
            res.tool_id = tool.id
        except Exception as e:
            logger.exception(f'Error create tool: {e}')
            raise e
        return res

    def compute_agent_tools(self):
        dynamic_variables_placeholders = dict(
            [(param.name, f'test_{param.name}') for param in self.params if param.value_type == 'dynamic_variable'])
        tool_config = None
        if self.tool_type == 'client':
            tool_config = {
                'type': self.tool_type,
                'name': self.name,
                'description': self.description,
                'parameters': [{
                    'type': param.data_type,
                    'description': param.description if param.value_type == 'description' else '',
                    'required': param.required,

                } for param in self.params],
                'expects_response': self.client_expects_response,
                'response_timeout_secs': self.response_timeout_secs,
                'dynamic_variables': {'dynamic_variable_placeholders': dynamic_variables_placeholders},
            }
            logger.info(f'Tool config: {json.dumps(tool_config, indent=2)}')
            return ToolRequestModelToolConfig_Client(**tool_config)
        elif self.tool_type == 'webhook':
            tool_config = {
                'type': self.tool_type,
                'description': self.description,
                'name': self.name,
                'dynamic_variables': {'dynamic_variable_placeholders': dynamic_variables_placeholders},
                'response_timeout_secs': self.response_timeout_secs,
                'api_schema': {
                    'method': self.method,
                    'url': self.get_tool_url(),
                    'query_params_schema': [{
                        'id': param.name,
                        'required': param.required,
                        'type': param.data_type,
                        'description': param.description if param.value_type == 'description' else '',
                        "constant_value": param.constant_value if param.value_type == 'constant_value' else '',
                        "dynamic_variable": param.dynamic_variable if param.value_type == 'dynamic_variable' else '',
                        "value_type": param.value_type
                    } for param in self.params]
                },
            }
            logger.info(f'Tool config: {json.dumps(tool_config, indent=2)}')
            return ToolRequestModelToolConfig_Webhook(**tool_config)


class ElevenlabsAgentToolparams(models.Model):
    _name = 'connect.agent_tool_params'
    _description = 'Elevenlabs Agent Tool Parameters'

    name = fields.Char(name='Identifier')
    data_type = fields.Selection(
        [('string', 'String'), ('boolean', 'Boolean'), ('integer', 'Integer')], default='string', required=True)
    required = fields.Boolean()
    value_type = fields.Selection(
        [('dynamic_variable', 'Dynamic Variable'), ('constant_value', 'Constant Value'), ('description', 'LLM Prompt')],
        default='description', required=True)
    constant_value = fields.Char()
    dynamic_variable = fields.Char()
    description = fields.Char()
    tool = fields.Many2one('connect.elevenlabs_agent_tool')

    @api.onchange('name')
    def _set_dynamic_variable(self):
        self.dynamic_variable = self.name
