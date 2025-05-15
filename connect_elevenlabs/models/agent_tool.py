# -*- coding: utf-8 -*-
import re
import urllib.parse

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ElevenlabsAgentTool(models.Model):
    _name = 'connect.elevenlabs_agent_tool'
    _description = 'Elevenlabs Agent Tool'
    _order = 'name'

    name = fields.Char(required=True)
    is_enabled = fields.Boolean(default=True, string='Enabled')
    description = fields.Char(required=True)
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
        return super().create(vals_list)


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
