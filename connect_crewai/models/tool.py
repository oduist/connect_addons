# -*- coding: utf-8 -*-
import datetime
import json
import logging
from odoo import models, fields
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext

logger = logging.getLogger(__name__)

# CrewAI 0.64+ exports BaseTool from crewai.tools
try:
    from crewai.tools import BaseTool
except ImportError:
    raise ValidationError(
        'crewai-tools is required to use Connect tools. Please install with: pip install crewai-tools'
    )

try:
    from pydantic import ConfigDict, Field
except ImportError:  # pragma: no cover - basic fallback
    ConfigDict = None

    def Field(default=None, **kwargs):  # type: ignore
        return default


class OdooRecordContextTool(BaseTool):
    """Tool to fetch a record payload and related chatter."""

    name: str = 'odoo_record_context'
    description: str = (
        'Fetch an Odoo record payload and its discussion thread (if available). '
        'Arguments: res_model (model name) and res_id (record ID).'
    )
    model_config = ConfigDict(arbitrary_types_allowed=True) if ConfigDict else None

    def __init__(self, env, **kwargs):
        super().__init__(**kwargs)
        self.env = env

    def _run(self, res_model: str, res_id: int, **kwargs):
        if not res_model or not res_id:
            raise ValueError('res_model and res_id are required')

        record = self.env[res_model].browse(int(res_id))
        if not record.exists():
            raise ValueError(f'Record not found for {res_model} with id {res_id}')

        payload = {
            'record': self._serialize_record(record),
            'messages': self._serialize_messages(record),
        }
        return json.dumps(payload, default=str)

    def _serialize_record(self, record):
        data = record.read()[0]
        return {key: self._serialize_value(value) for key, value in data.items()}

    def _serialize_messages(self, record):
        if 'message_ids' not in record._fields:
            return []

        messages = record.message_ids.sorted(key=lambda m: m.date or m.create_date or datetime.datetime.min)
        return [
            {
                'id': msg.id,
                'date': (msg.date or msg.create_date).isoformat() if (msg.date or msg.create_date) else None,
                'author': msg.author_id.display_name or msg.email_from,
                'subject': msg.subject,
                'body': html2plaintext(msg.body or '').strip(),
                'message_type': msg.message_type,
                'subtype': msg.subtype_id.name,
            }
            for msg in messages
        ]

    def _serialize_value(self, value):
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='ignore')
        if isinstance(value, (list, tuple)):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._serialize_value(val) for key, val in value.items()}
        return value


class OdooMessagePostTool(BaseTool):
    """Tool to post a message to a record's chatter."""

    name: str = 'odoo_message_post'
    description: str = (
        'Post a message to an Odoo record. Arguments: res_model (model name), '
        'res_id (record ID), and message (comment body).'
    )
    message: str = Field(default='', description='Message body to post')
    model_config = ConfigDict(arbitrary_types_allowed=True) if ConfigDict else None

    def __init__(self, env, **kwargs):
        super().__init__(**kwargs)
        self.env = env

    def _run(self, res_model: str, res_id: int, message: str, **kwargs):
        if not message:
            raise ValueError('Message body is required')
        if not res_model or not res_id:
            raise ValueError('res_model and res_id are required')

        record = self.env[res_model].browse(int(res_id))
        if not record.exists():
            raise ValueError(f'Record not found for {res_model} with id {res_id}')

        record.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return f'Message posted to {res_model} with id {res_id}'


class ConnectTool(models.Model):
    _name = 'connect.tool'
    _description = 'Connect Tool'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help='Internal code used to initialize the tool')
    description = fields.Text()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('connect_tool_code_unique', 'unique(code)', 'Tool code must be unique.'),
    ]

    def get_crewai_tools(self):
        tools = []
        for tool in self:
            instance = tool._instantiate_tool()
            if instance:
                tools.append(instance)
        return tools

    def _instantiate_tool(self):
        self.ensure_one()
        factory = self._get_tool_factories().get(self.code)
        if not factory:
            logger.warning('No tool factory found for code %s', self.code)
            return None
        try:
            return factory(self.env)
        except Exception as exc:  # pragma: no cover - defensive catch for runtime tool creation
            logger.warning('Failed to initialize tool %s: %s', self.code, exc)
            return None

    @classmethod
    def _get_tool_factories(cls):
        factories = {}

        try:
            from crewai_tools import (
                SerperDevTool,
                WebsiteSearchTool,
                FileReadTool,
                DirectoryReadTool,
                CodeInterpreterTool,
            )

            factories.update({
                'search_tool': lambda env: SerperDevTool(),
                'website_search_tool': lambda env: WebsiteSearchTool(),
                'file_read_tool': lambda env: FileReadTool(),
                'directory_read_tool': lambda env: DirectoryReadTool(),
                'code_interpreter_tool': lambda env: CodeInterpreterTool(),
            })
        except ImportError:
            logger.warning('crewai_tools not installed, built-in tool wrappers will be unavailable')

        factories.update({
            'odoo_record_context': lambda env: OdooRecordContextTool(env=env),
            'odoo_message_post': lambda env: OdooMessagePostTool(env=env),
        })
        return factories
