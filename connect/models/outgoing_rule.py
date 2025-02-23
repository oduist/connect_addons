# -*- coding: utf-8 -*-

import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import debug

logger = logging.getLogger(__name__)


class OutgoingRule(models.Model):
    _name = 'connect.outgoing_rule'
    _description = 'Outgoing Rule'
    _order = 'pattern'

    name = fields.Char(required=True)
    byoc = fields.Many2one('connect.byoc', string='BYOC', ondelete='set null')
    pattern = fields.Char(required=True)
    is_enabled = fields.Boolean(string='Enabled', default=True)

    @api.model
    def find_rule(self, number):
        rules = {}
        for rule in self.sudo().search([('is_enabled', '=', True)]):
            if re.match(r'^\{}'.format(rule.pattern), number):
                rules[rule.pattern] = rule.id
        # Get the deepest match.
        if rules:
            keys = list(rules.keys())
            keys.sort()
            last_rule = keys[-1]
            debug(self, 'Found rule ID {} pattern {}.'.format(rules[last_rule], last_rule))
            return self.browse(rules[last_rule])
        else:
            logger.error('No rules found for number %s', number)

    @api.constrains('pattern')
    def check_pattern(self):
        for rec in self:
            if rec.pattern and not rec.pattern.startswith('+'):
                raise ValidationError('Pattern must start with +')
