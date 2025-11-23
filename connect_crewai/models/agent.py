# -*- coding: utf-8 -*-
import logging
import os
from odoo import models, fields, api
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class CrewAIAgent(models.Model):
    _name = 'connect.crewai_agent'
    _description = 'CrewAI Agent'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Agent Name', required=True, tracking=True)
    role = fields.Char(
        string='Role',
        required=True,
        tracking=True,
        help='The role of the agent (e.g., "Senior Research Analyst", "Content Writer")'
    )
    goal = fields.Text(
        string='Goal',
        required=True,
        tracking=True,
        help='The goal the agent is trying to achieve'
    )
    backstory = fields.Text(
        string='Backstory',
        required=True,
        tracking=True,
        help='The backstory of the agent that adds context to its role'
    )
    verbose = fields.Boolean(
        string='Verbose',
        default=True,
        tracking=True,
        help='Enable verbose output during execution'
    )
    allow_delegation = fields.Boolean(
        string='Allow Delegation',
        default=False,
        tracking=True,
        help='Allow this agent to delegate tasks to other agents'
    )
    llm_provider = fields.Selection([
        ('openai', 'OpenAI'),
        ('anthropic', 'Anthropic'),
        ('google', 'Google'),
        ('ollama', 'Ollama (Local)'),
    ], string='LLM Provider', default='openai', required=True, tracking=True)
    llm_model = fields.Char(
        string='LLM Model',
        default='gpt-4o',
        required=True,
        tracking=True,
        help='The LLM model to use (e.g., gpt-4o, claude-3-5-sonnet-20241022, gemini-pro)'
    )
    temperature = fields.Float(
        string='Temperature',
        default=0.7,
        required=True,
        tracking=True,
        help='Controls randomness. Lower values make output more focused and deterministic (0.0-2.0)'
    )
    max_iter = fields.Integer(
        string='Max Iterations',
        default=25,
        required=True,
        tracking=True,
        help='Maximum number of iterations before the agent stops'
    )
    max_rpm = fields.Integer(
        string='Max RPM',
        help='Maximum requests per minute for rate limiting (optional)'
    )
    max_execution_time = fields.Integer(
        string='Max Execution Time (seconds)',
        help='Maximum execution time in seconds (optional)'
    )
    tools = fields.Text(
        string='Tools (deprecated)',
        help='Comma-separated list of tool names the agent can use (legacy support)'
    )
    tool_ids = fields.Many2many(
        'connect.tool',
        'crewai_agent_tool_rel',
        'agent_id',
        'tool_id',
        string='Tools',
        domain=[('active', '=', True)],
        help='Tools available to this agent'
    )
    function_calling_llm_model = fields.Char(
        string='Function Calling LLM',
        help='Specific LLM model for function calling (optional, uses main LLM if not set)'
    )
    crew_ids = fields.Many2many(
        'connect.crewai_crew',
        'crewai_crew_agent_rel',
        'agent_id',
        'crew_id',
        string='Crews'
    )
    active = fields.Boolean(default=True)

    @api.constrains('temperature')
    def _check_temperature(self):
        for rec in self:
            if rec.temperature < 0.0 or rec.temperature > 2.0:
                raise ValidationError('Temperature must be between 0.0 and 2.0')

    @api.constrains('max_iter')
    def _check_max_iter(self):
        for rec in self:
            if rec.max_iter < 1:
                raise ValidationError('Max iterations must be at least 1')

    def get_crewai_agent(self):
        self.ensure_one()
        try:
            from crewai import Agent
        except ImportError:
            raise ValidationError('CrewAI library is not installed. Please install it with: pip install crewai')

        llm = self._get_llm()

        tools = self._get_tool_instances()

        agent_config = {
            'role': self.role,
            'goal': self.goal,
            'backstory': self.backstory,
            'verbose': self.verbose,
            'allow_delegation': self.allow_delegation,
            'max_iter': self.max_iter,
        }

        if llm:
            agent_config['llm'] = llm
        if tools:
            agent_config['tools'] = tools
        if self.max_rpm:
            agent_config['max_rpm'] = self.max_rpm
        if self.max_execution_time:
            agent_config['max_execution_time'] = self.max_execution_time
        if self.function_calling_llm_model:
            agent_config['function_calling_llm'] = self._get_function_calling_llm()

        return Agent(**agent_config)

    def _get_llm(self):
        try:
            from langchain_openai import ChatOpenAI
            from langchain_anthropic import ChatAnthropic
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_community.llms import Ollama
        except ImportError:
            logger.warning('LangChain libraries not fully installed')
            return None

        settings = self.env['connect.settings'].sudo()

        if self.llm_provider == 'openai':
            api_key = settings.get_param('openai_api_key')
            if not api_key:
                raise ValidationError('OpenAI API key not configured in Connect Settings')
            os.environ.setdefault('OPENAI_API_KEY', api_key)
            return ChatOpenAI(
                model=self.llm_model,
                temperature=self.temperature,
                api_key=api_key
            )
        elif self.llm_provider == 'anthropic':
            api_key = settings.get_param('anthropic_api_key')
            if not api_key:
                raise ValidationError('Anthropic API key not configured')
            os.environ.setdefault('ANTHROPIC_API_KEY', api_key)
            return ChatAnthropic(
                model=self.llm_model,
                temperature=self.temperature,
                api_key=api_key
            )
        elif self.llm_provider == 'google':
            api_key = settings.get_param('google_api_key')
            if not api_key:
                raise ValidationError('Google API key not configured')
            os.environ.setdefault('GOOGLE_API_KEY', api_key)
            return ChatGoogleGenerativeAI(
                model=self.llm_model,
                temperature=self.temperature,
                google_api_key=api_key
            )
        elif self.llm_provider == 'ollama':
            return Ollama(
                model=self.llm_model,
                temperature=self.temperature
            )

        return None

    def _get_function_calling_llm(self):
        if not self.function_calling_llm_model:
            return None

        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            return None

        settings = self.env['connect.settings'].sudo()
        api_key = settings.get_param('openai_api_key')
        if not api_key:
            return None
        os.environ.setdefault('OPENAI_API_KEY', api_key)

        return ChatOpenAI(
            model=self.function_calling_llm_model,
            temperature=self.temperature,
            api_key=api_key
        )

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
