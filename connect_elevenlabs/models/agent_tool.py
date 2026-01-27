# -*- coding: utf-8 -*-
import json
import re
import urllib.parse
import logging

from odoo import models, fields, api, release
from odoo.exceptions import ValidationError
from elevenlabs import ToolRequestModel

logger = logging.getLogger(__name__)
if release.version_info[0] >= 19:
    from odoo.models import Constraint


class ElevenlabsAgentTool(models.Model):
    _name = 'connect.elevenlabs_agent_tool'
    _description = 'Elevenlabs Agent Tool'
    _order = 'tool_type ASC, name ASC'

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

    # Use modern constraint syntax for Odoo 19, fallback to legacy for older versions
    if release.version_info[0] >= 19:
        _name_unique = Constraint('UNIQUE(name)', 'This name is already used!')
    else:
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
        if res.tool_type != 'system':
            client = self.env['connect.settings'].get_elevenlabs_client()
            try:
                # Create tool using ElevenLabs API
                tool_config = res.compute_agent_tools_config()
                tool = client.conversational_ai.tools.create(
                    request=ToolRequestModel(tool_config=tool_config)
                )

                res.tool_id = tool.id
                logger.info(f'Successfully created tool: {res.name} with ID: {tool.id}')

            except Exception as e:
                logger.exception(f'Error creating tool {res.name}: {e}')
                raise ValidationError(f'Failed to create ElevenLabs tool: {str(e)}')
        return res

    def compute_agent_tools_config(self):
        """Compute tool configuration using plain dictionaries (fallback method)"""
        try:
            if self.tool_type == 'client':
                # Build client tool configuration
                parameters = {}
                required = []

                for param in self.params:
                    parameters[param.name] = {
                        'type': param.data_type,
                        'description': param.description if param.value_type == 'description' else param.name
                    }
                    if param.required:
                        required.append(param.name)


                tool_config = {
                    'name': self.name,
                    'description': self.description,
                    'expects_response': self.client_expects_response,
                    'parameters': {
                        'type': 'object',
                        'properties': parameters,
                        'required': required
                    } if parameters else {},
                    'response_timeout_secs': self.response_timeout_secs,
                }


            elif self.tool_type == 'webhook':
                # Build webhook tool configuration
                api_schema = {
                    'method': self.method,
                    'url': self.get_tool_url(),
                }

                # Add request body schema for body parameters
                if self.param_type == 'body':
                    properties = {}
                    required = []

                    if self.params:
                        for param in self.params:
                            properties[param.name] = {
                                'type': param.data_type,
                                'description': param.description if param.value_type == 'description' else param.name
                            }
                            if param.required:
                                required.append(param.name)

                    api_schema['request_body_schema'] = {
                        'type': 'object',
                        'properties': properties,
                        'required': required
                    }

                tool_config = {
                    'name': self.name,
                    'description': self.description,
                    'api_schema': api_schema,
                    'response_timeout_secs': self.response_timeout_secs,
                }

            else:
                # System tools or other types
                tool_config = {
                    'name': self.name,
                    'description': self.description,
                    'type': self.tool_type,
                }


            logger.info(f'Dict-based tool config: {json.dumps(tool_config, indent=2)}')
            return tool_config

        except Exception as e:
            logger.error(f'Error creating dict-based tool config: {e}')
            raise ValidationError(f'Failed to create tool configuration: {str(e)}')

    def write(self, vals):
        """Override write to update tool in ElevenLabs when changed"""
        result = super().write(vals)

        # Update tool in ElevenLabs if it exists and we're not in a skip context
        if self.tool_id and not self.env.context.get('skip_elevenlabs'):
            try:
                self.update_elevenlabs_tool()
            except Exception as e:
                logger.warning(f'Failed to update ElevenLabs tool {self.name}: {e}')
                # Don't fail the write operation, just log the warning

        return result

    def unlink(self):
        """Override unlink to delete tool from ElevenLabs"""
        for record in self:
            if record.tool_id:
                try:
                    record.delete_elevenlabs_tool()
                except Exception as e:
                    logger.warning(f'Failed to delete ElevenLabs tool {record.name}: {e}')
                    # Continue with deletion even if ElevenLabs deletion fails

        return super().unlink()

    def update_elevenlabs_tool(self):
        """Update tool in ElevenLabs"""
        if not self.tool_id:
            return

        client = self.env['connect.settings'].get_elevenlabs_client()

        try:
            # Try model-based approach first
            tool_config = self.compute_agent_tools_config()

            response = client.conversational_ai.tools.update(
                tool_id=self.tool_id,
                request=ToolRequestModel(tool_config=tool_config)
            )

            logger.info(f'Successfully updated ElevenLabs tool: {self.name}')

        except Exception as e:
            logger.error(f'Error updating ElevenLabs tool {self.name}: {e}')
            raise ValidationError(f'Failed to update ElevenLabs tool: {str(e)}')

    def delete_elevenlabs_tool(self):
        """Delete tool from ElevenLabs"""
        if not self.tool_id:
            return

        client = self.env['connect.settings'].get_elevenlabs_client()

        try:
            client.conversational_ai.tools.delete(tool_id=self.tool_id)
            logger.info(f'Successfully deleted ElevenLabs tool: {self.name}')

        except Exception as e:
            logger.error(f'Error deleting ElevenLabs tool {self.name}: {e}')
            raise ValidationError(f'Failed to delete ElevenLabs tool: {str(e)}')

    def action_sync_with_elevenlabs(self):
        """Action to sync tool with ElevenLabs"""
        try:
            if self.tool_id:
                self.update_elevenlabs_tool()
                message = f"Tool '{self.name}' updated successfully"
            else:
                # Create if doesn't exist
                client = self.env['connect.settings'].get_elevenlabs_client()
                tool_config = self.compute_agent_tools_config()

                tool = client.conversational_ai.tools.create(
                    request=ToolRequestModel(tool_config=tool_config)
                )

                self.tool_id = tool.id
                message = f"Tool '{self.name}' created successfully with ID: {tool.id}"

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Tool Sync Success',
                    'message': message,
                    'type': 'success',
                }
            }

        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Tool Sync Failed',
                    'message': f'Error syncing tool: {str(e)}',
                    'type': 'danger',
                }
            }


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
