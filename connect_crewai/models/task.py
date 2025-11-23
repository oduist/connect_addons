# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class CrewAITask(models.Model):
    _name = 'connect.crewai_task'
    _description = 'CrewAI Task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    name = fields.Char(string='Task Name', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(
        string='Description',
        required=True,
        tracking=True,
        help='Clear description of what the task entails'
    )
    expected_output = fields.Text(
        string='Expected Output',
        required=True,
        tracking=True,
        help='Clear definition of expected output for the task'
    )
    agent_id = fields.Many2one(
        'connect.crewai_agent',
        string='Agent',
        required=True,
        tracking=True,
        help='The agent responsible for this task'
    )
    crew_id = fields.Many2one(
        'connect.crewai_crew',
        string='Crew',
        tracking=True,
        ondelete='cascade'
    )
    context = fields.Text(
        string='Context',
        help='Additional context that will be provided to the task'
    )
    async_execution = fields.Boolean(
        string='Async Execution',
        default=False,
        tracking=True,
        help='Execute this task asynchronously'
    )
    output_file = fields.Char(
        string='Output File',
        help='File path to save the task output (optional)'
    )
    tools = fields.Text(
        string='Task-Specific Tools (deprecated)',
        help='Comma-separated list of tool names specific to this task (legacy support)'
    )
    tool_ids = fields.Many2many(
        'connect.tool',
        'crewai_task_tool_rel',
        'task_id',
        'tool_id',
        string='Task Tools',
        domain=[('active', '=', True)],
        help='Tools specific to this task (overrides agent tools)'
    )
    active = fields.Boolean(default=True)

    def get_crewai_task(self, agent=None):
        self.ensure_one()
        try:
            from crewai import Task
        except ImportError:
            raise ValidationError('CrewAI library is not installed. Please install it with: pip install crewai')

        if not agent:
            agent = self.agent_id.get_crewai_agent()

        task_config = {
            'description': self.description,
            'expected_output': self.expected_output,
            'agent': agent,
        }

        if self.context:
            task_config['context'] = self.context
        if self.async_execution:
            task_config['async_execution'] = self.async_execution
        if self.output_file:
            task_config['output_file'] = self.output_file
        tools = self._get_tool_instances()
        if tools:
            task_config['tools'] = tools

        return Task(**task_config)

    def _get_tool_instances(self):
        tools = []
        if self.tool_ids:
            tools.extend(self.tool_ids.get_crewai_tools())
        if self.tools:
            tools.extend(self._parse_tools_from_text())
        return [tool for tool in tools if tool]

    def _parse_tools_from_text(self):
        if not self.tools:
            return []

        try:
            tool_mapping = self.env['connect.tool']._get_tool_factories()
        except Exception:
            tool_mapping = {}

        tools = []
        tool_names = [t.strip().lower() for t in self.tools.split(',') if t.strip()]

        for tool_name in tool_names:
            factory = tool_mapping.get(tool_name)
            if factory:
                try:
                    tools.append(factory(self.env))
                except Exception as e:
                    logger.warning(f'Failed to initialize tool {tool_name}: {e}')

        return tools
