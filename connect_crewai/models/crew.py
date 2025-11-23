# -*- coding: utf-8 -*-
import logging
import json
import numbers
from datetime import datetime
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

logger = logging.getLogger(__name__)


class CrewAICrew(models.Model):
    _name = 'connect.crewai_crew'
    _description = 'CrewAI Crew'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Crew Name', required=True, tracking=True)
    description = fields.Text(string='Description', tracking=True)
    agent_ids = fields.Many2many(
        'connect.crewai_agent',
        'crewai_crew_agent_rel',
        'crew_id',
        'agent_id',
        string='Agents',
        tracking=True,
        help='Agents that are part of this crew'
    )
    task_ids = fields.One2many(
        'connect.crewai_task',
        'crew_id',
        string='Tasks',
        tracking=True
    )
    process = fields.Selection([
        ('sequential', 'Sequential'),
        ('hierarchical', 'Hierarchical'),
    ], string='Process Type', default='sequential', required=True, tracking=True,
       help='Sequential: Tasks executed in order. Hierarchical: Manager agent delegates tasks.')
    verbose = fields.Boolean(
        string='Verbose',
        default=True,
        tracking=True,
        help='Enable verbose output during crew execution'
    )
    manager_llm = fields.Char(
        string='Manager LLM',
        help='LLM model for the manager agent (only for hierarchical process)'
    )
    max_rpm = fields.Integer(
        string='Max RPM',
        help='Maximum requests per minute for the entire crew (optional)'
    )
    memory = fields.Boolean(
        string='Enable Memory',
        default=False,
        tracking=True,
        help='Enable memory for agents to remember past interactions'
    )
    cache = fields.Boolean(
        string='Enable Cache',
        default=True,
        tracking=True,
        help='Enable caching to improve performance'
    )
    execution_ids = fields.One2many(
        'connect.crewai_execution',
        'crew_id',
        string='Executions'
    )
    execution_count = fields.Integer(
        string='Execution Count',
        compute='_compute_execution_count'
    )
    active = fields.Boolean(default=True)

    @api.depends('execution_ids')
    def _compute_execution_count(self):
        for rec in self:
            rec.execution_count = len(rec.execution_ids)

    @api.constrains('process', 'manager_llm')
    def _check_hierarchical_config(self):
        for rec in self:
            if rec.process == 'hierarchical' and not rec.manager_llm:
                raise ValidationError('Manager LLM is required for hierarchical process')

    def action_execute_crew(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Execute Crew',
            'res_model': 'connect.crewai_execution',
            'view_mode': 'form',
            'context': {
                'default_crew_id': self.id,
                'default_state': 'draft',
            },
            'target': 'new',
        }

    def execute_crew(self, inputs=None):
        self.ensure_one()

        if not self.agent_ids:
            raise ValidationError('Crew must have at least one agent')
        if not self.task_ids:
            raise ValidationError('Crew must have at least one task')

        execution = self.env['connect.crewai_execution'].create({
            'crew_id': self.id,
            'state': 'running',
            'start_time': fields.Datetime.now(),
            'inputs': json.dumps(inputs) if inputs else '{}',
        })

        try:
            result = self._run_crew(inputs)
            execution.write({
                'state': 'done',
                'end_time': fields.Datetime.now(),
                'result': result.get('result', ''),
                'output': result.get('output', ''),
                'token_usage': result.get('token_usage', 0),
            })
            return execution
        except Exception as e:
            logger.exception('Error executing crew: %s', e)
            execution.write({
                'state': 'error',
                'end_time': fields.Datetime.now(),
                'error_message': str(e),
            })
            raise UserError(f'Error executing crew: {str(e)}')

    def _run_crew(self, inputs=None):
        self.ensure_one()
        try:
            from crewai import Crew, Process
        except ImportError:
            raise ValidationError('CrewAI library is not installed. Please install it with: pip install crewai')

        agents = []
        agent_map = {}
        for agent_record in self.agent_ids:
            crewai_agent = agent_record.get_crewai_agent()
            agents.append(crewai_agent)
            agent_map[agent_record.id] = crewai_agent

        tasks = []
        for task_record in self.task_ids.sorted('sequence'):
            agent = agent_map.get(task_record.agent_id.id)
            if not agent:
                raise ValidationError(f'Agent {task_record.agent_id.name} not found in crew')
            crewai_task = task_record.get_crewai_task(agent=agent)
            tasks.append(crewai_task)

        crew_config = {
            'agents': agents,
            'tasks': tasks,
            'process': Process.sequential if self.process == 'sequential' else Process.hierarchical,
            'verbose': self.verbose,
            'cache': self.cache,
        }

        if self.memory:
            crew_config['memory'] = True
        if self.max_rpm:
            crew_config['max_rpm'] = self.max_rpm
        if self.process == 'hierarchical' and self.manager_llm:
            crew_config['manager_llm'] = self._get_manager_llm()

        crew = Crew(**crew_config)

        result = crew.kickoff(inputs=inputs or {})

        output_data = {
            'result': str(result),
            'output': str(result),
            'token_usage': self._extract_token_usage(getattr(result, 'token_usage', 0)),
        }

        return output_data

    def _extract_token_usage(self, usage):
        """Normalize token usage to an integer."""
        if isinstance(usage, numbers.Number):
            return int(usage)

        # Dataclass-like with common attributes
        for attr in ('total_tokens', 'total', 'tokens', 'prompt_tokens', 'completion_tokens', 'input_tokens', 'output_tokens'):
            value = getattr(usage, attr, None)
            if isinstance(value, numbers.Number):
                return int(value)

        # Dict-like object
        if isinstance(usage, dict):
            # prefer keys in order
            for key in ('total_tokens', 'total', 'tokens', 'prompt_tokens', 'completion_tokens', 'input_tokens', 'output_tokens'):
                if key in usage and isinstance(usage[key], numbers.Number):
                    return int(usage[key])
            # fallback: sum numeric values
            numeric_values = [v for v in usage.values() if isinstance(v, numbers.Number)]
            if numeric_values:
                return int(sum(numeric_values))

        logger.warning('Unable to parse token usage from %s; defaulting to 0', usage)
        return 0

    def _get_manager_llm(self):
        if not self.manager_llm:
            return None

        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            return None

        settings = self.env['connect.settings'].sudo()
        api_key = settings.get_param('openai_api_key')
        if not api_key:
            raise ValidationError('OpenAI API key not configured in Connect Settings')

        return ChatOpenAI(
            model=self.manager_llm,
            temperature=0.7,
            api_key=api_key
        )

    def action_view_executions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crew Executions',
            'res_model': 'connect.crewai_execution',
            'view_mode': 'list,form',
            'domain': [('crew_id', '=', self.id)],
            'context': {'default_crew_id': self.id},
        }
