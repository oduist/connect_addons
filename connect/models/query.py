# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import ast
import json
import logging
from urllib.parse import urljoin
from odoo import api, fields, models
import openai


logger = logging.getLogger(__name__)


class Query(models.Model):
    _name = 'connect.query'
    _description = 'Query'
    _rec_name = 'id'

    prompt = fields.Text()
    sources = fields.Many2many('connect.query_source')
    result = fields.Text(readonly=True)
    status = fields.Selection(default='draft', readonly=True, selection=[
        ('draft', 'draft'),
        ('process', 'process'),
        ('done', 'done'),
        ('error', 'error'),
    ])
    price = fields.Float(default=0, digits=(16, 3), readonly=True)
    error = fields.Char(readonly=True)
    token = fields.Char()
    query_prompt = fields.Many2one('connect.query_prompt')

    def get_ai_client(self):
        api_key = self.env['connect.settings'].get_param('openai_api_key')
        if not api_key:
            return False
        return openai.OpenAI(api_key=api_key)

    def submit_query(self):
        self.ensure_one()
        client = self.get_ai_client()
        if not client:
            self.error = 'Missing "openai_api_key"! Check -> Connect/Settings/General/API Keys!'
            return False
        if self.error:
            self.error = False

        settings = self.env['connect.settings']
        api_url = settings.get_param('api_url')
        url = urljoin(api_url, 'ai_query')
        data = {}
        for rule in self.sources:
            domain = ast.literal_eval(rule.domain) if rule.domain else []
            read_fields = [field.name for field in rule.field_ids]
            data.update({rule.model_id.name: self.env[rule.model_id.model].search(domain).read(read_fields)})

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": json.dumps(data)}
                ]
            )
            self.result = response.choices[0].message.content
        except openai.AuthenticationError as e:
            self.error = "Authentication error: {}".format(e)

    @api.onchange('query_prompt')
    def _on_change_query_prompt(self):
        self.prompt = self.query_prompt.content
