# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ElevenlabsAgentTool(models.Model):
    _name = 'connect.elevenlabs_agent_tool'
    _description = 'Elevenlabs Agent Tool'

    name = fields.Char(required=True)
    description = fields.Char(required=True)
    tool_type = fields.Selection(
        [('client', 'Client'), ('webhook', 'Webhook'), ('system', 'System')], default='webhook', required=True)
    url = fields.Char()
    method = fields.Selection(
        [('GET', 'GET'), ('POST', 'POST'), ('PATCH', 'PATCH'), ('PUT', 'PUT'), ('DELETE', 'DELETE')], default='POST')
    props = fields.One2many('connect.agent_tool_props', 'tool', string='Properties')
    body_props_description = fields.Char()
    response_timeout_secs = fields.Integer(default=20, string='Response Timeout')
    param_type = fields.Selection([('query', 'query'), ('path', 'path'), ('body', 'body')], default='body')

    @api.constrains('response_timeout_secs')
    def _check_response_timeout_secs(self):
        for rec in self:
            if rec.response_timeout_secs and rec.response_timeout_secs <= 120 or rec.response_timeout_secs >= 5:
                raise ValidationError('Please enter a response timeout value between 5 and 120')

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)


class ElevenlabsAgentToolProps(models.Model):
    _name = 'connect.agent_tool_props'
    _description = 'Elevenlabs Agent Tool'

    name = fields.Char(name='Identifier')
    data_type = fields.Selection(
        [('string', 'String'), ('boolean', 'Boolean'), ('integer', 'Integer')], default='string', required=True)
    required = fields.Boolean()
    value_type = fields.Selection(
        [('dynamic_variable', 'Dynamic Variable'), ('constant', 'Constant Variable'), ('llm_prompt', 'LLM Prompt')],
        default='llm_prompt', required=True)
    constant_value = fields.Char()
    dynamic_variable = fields.Char()
    description = fields.Char()
    tool = fields.Many2one('connect.elevenlabs_agent_tool')

    @api.onchange('name')
    def _set_dynamic_variable(self):
        self.dynamic_variable = self.name
