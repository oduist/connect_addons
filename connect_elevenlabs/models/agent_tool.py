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
    synced = fields.Boolean(default=False, string='Synced to ElevenLabs')
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
        if res.tool_type != 'system' and not self.env.context.get('install_mode'):
            res._sync_to_elevenlabs()
        return res

    def compute_agent_tools_config(self):
        """Compute tool configuration using plain dictionaries (fallback method)"""
        try:
            dynamic_variable_placeholders = {}
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
                            }
                            if param.value_type == 'dynamic_variable':
                                properties[param.name].update({'dynamic_variable': param.name})
                                dynamic_variable_placeholders.update({param.name: "default"})
                            else:
                                properties[param.name].update({
                                    'description': param.description if param.value_type == 'description' else param.name
                                })
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
                    'dynamic_variables': dynamic_variable_placeholders,
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
        print(vals)
        """Override write to update tool in ElevenLabs when changed"""
        result = super().write(vals)
        if not self.env.context.get('skip_elevenlabs') or not self.env.context.get('install_mode'):
            for record in self:
                if record.synced and record.tool_id:
                    try:
                        record.update_elevenlabs_tool()
                    except Exception as e:
                        logger.warning(f'Failed to update ElevenLabs tool {record.name}: {e}')
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

    def _sync_to_elevenlabs(self):
        """Internal method to sync tool to ElevenLabs"""
        client = self.env['connect.settings'].get_elevenlabs_client()
        try:
            tool_config = self.compute_agent_tools_config()
            tool = client.conversational_ai.tools.create(
                request=ToolRequestModel(tool_config=tool_config)
            )
            self.write({'tool_id': tool.id, 'synced': True})
            logger.info(f'Successfully synced tool: {self.name} with ID: {tool.id}')
        except Exception as e:
            logger.error(f'Error syncing tool {self.name}: {e}')
            raise ValidationError(f'Failed to sync ElevenLabs tool: {str(e)}')

    def remove_all_from_elevenlabs(self):
        """Delete all tools from ElevenLabs and mark all Odoo tools as not synced"""
        client = self.env['connect.settings'].get_elevenlabs_client()
        deleted_count = 0
        failed_tools = []
        try:
            response = client.conversational_ai.tools.list()
            elevenlabs_tools = response.tools if hasattr(response, 'tools') else []
        except Exception as e:
            logger.error(f'Failed to fetch tools from ElevenLabs: {e}')
            raise ValidationError(f'Failed to fetch tools from ElevenLabs: {str(e)}')
        for tool in elevenlabs_tools:
            tool_id = tool.id if hasattr(tool, 'id') else tool.get('id')
            tool_name = tool_id
            try:
                client.conversational_ai.tools.delete(tool_id=tool_id)
                deleted_count += 1
            except Exception as e:
                failed_tools.append(f"{tool_name}: {str(e)}")
                logger.warning(f'Failed to delete ElevenLabs tool {tool_name}: {e}')
        self.search([]).with_context(skip_elevenlabs=True).write({'synced': False, 'tool_id': False})
        message = f'Deleted {deleted_count} tool(s) from ElevenLabs'
        msg_type = 'success'
        if failed_tools:
            message += f'. Failed: {", ".join(failed_tools)}'
            msg_type = 'warning' if deleted_count > 0 else 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Remove All Tools',
                'message': message,
                'type': msg_type,
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
    description = fields.Text()
    tool = fields.Many2one('connect.elevenlabs_agent_tool')

    @api.onchange('name')
    def _set_dynamic_variable(self):
        self.dynamic_variable = self.name
