# -*- coding: utf-8 -*-
import logging
import json
from odoo import models, fields, api
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class CrewAIExecution(models.Model):
    _name = 'connect.crewai_execution'
    _description = 'CrewAI Execution'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Execution Name', compute='_compute_name', store=True)
    crew_id = fields.Many2one(
        'connect.crewai_crew',
        string='Crew',
        required=True,
        tracking=True,
        ondelete='cascade'
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], string='State', default='draft', required=True, tracking=True)
    inputs = fields.Text(
        string='Inputs (JSON)',
        help='Input parameters for the crew execution in JSON format'
    )
    result = fields.Text(string='Result', readonly=True)
    output = fields.Text(string='Full Output', readonly=True)
    error_message = fields.Text(string='Error Message', readonly=True)
    start_time = fields.Datetime(string='Start Time', readonly=True)
    end_time = fields.Datetime(string='End Time', readonly=True)
    duration = fields.Float(
        string='Duration (seconds)',
        compute='_compute_duration',
        store=True
    )
    token_usage = fields.Integer(string='Token Usage', readonly=True)

    @api.depends('crew_id', 'create_date')
    def _compute_name(self):
        for rec in self:
            if rec.crew_id:
                rec.name = f"{rec.crew_id.name} - {rec.create_date.strftime('%Y-%m-%d %H:%M:%S') if rec.create_date else 'New'}"
            else:
                rec.name = 'New Execution'

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for rec in self:
            if rec.start_time and rec.end_time:
                delta = rec.end_time - rec.start_time
                rec.duration = delta.total_seconds()
            else:
                rec.duration = 0.0

    def action_execute(self):
        self.ensure_one()
        
        if self.state not in ('draft', 'error'):
            raise ValidationError('Can only execute executions in Draft or Error state')

        inputs = {}
        if self.inputs:
            try:
                inputs = json.loads(self.inputs)
            except json.JSONDecodeError:
                raise ValidationError('Inputs must be valid JSON')

        self.crew_id.execute_crew(inputs=inputs)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_view_crew(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crew',
            'res_model': 'connect.crewai_crew',
            'res_id': self.crew_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
