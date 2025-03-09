# -*- coding: utf-8 -*-

import logging
from odoo import fields, models, api, release
from twilio.twiml.voice_response import Gather, VoiceResponse, Say, Hangup
from .twiml import pretty_xml

logger = logging.getLogger(__name__)


class Exten(models.Model):
    _name = 'connect.exten'
    _description = 'Exten'
    _order = 'number'

    name = fields.Char(compute='_get_name', store=True, copy=False)
    number = fields.Char('Extension Number', required=True, copy=False)
    model = fields.Char('AppModel')
    model_friendly = fields.Char('Model', compute='_get_name', store=True, copy=False)
    res_id = fields.Integer()
    dst = fields.Reference(
        string='Destination',
        required=True,
        selection=[
            ('connect.user', 'User'),
            ('connect.callflow', 'Call Flow'),
            ('connect.twiml', 'TwiML')],
        compute='_get_dst', inverse='_set_dst')
    dst_name = fields.Char(compute='_get_dst')
    twiml = fields.Text('TwiML', compute='_get_twiml', readonly=True)

    _sql_constraints = [
        ('number_uniq', 'UNIQUE(number)', 'This extension number is already defined in the domain!')
    ]

    @api.depends('number', 'model', 'res_id', 'dst')
    def _get_name(self):
        for rec in self:
            try:
                rec.name = "{} <{}>".format(rec.number, rec.dst.name if rec.dst else '')
                rec.model_friendly = dict(
                    self.env['connect.exten']._fields['dst'].selection).get(rec.model)
            except Exception as e:
                logger.exception('Exten name error:')
                rec.name = 'See Odoo Error Log'
                rec.model_friendly = ''

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        for record in res:
            if hasattr(record.dst, 'exten'):
                record.dst.exten = record
        return res

    def write(self, vals):
        if (self.model is not False) and ('model' in vals) and ('res_id' in vals):
            self.env[self.model].search([('exten', '=', self.id)]).update({'exten': False})
            self.env['connect.exten'].search([
                ('res_id', '=', vals['res_id']), ('model', '=', vals['model'])]).update({'res_id': False})
        res = super().write(vals)
        if hasattr(self.dst, 'exten'):
            self.dst.exten = self
        return res

    def unlink(self):
        for rec in self:
            if hasattr(rec.dst, 'exten'):
                rec.dst.exten = False
        return super().unlink()

    def copy_data(self, default=None):
        default = dict(default or {})
        data_list = super().copy_data(default)
        extensions = self.search([('model', '=', data_list[0]['model'])])
        last_number = extensions[-1].number
        new_number = int(last_number) + 1
        data_list[0]['number'] = str(new_number)
        return data_list

    def _get_dst(self):
        # We need a reference field to be computed because we want to
        # search and group by model.
        for rec in self:
            if rec.model and rec.model in self.env:
                try:
                    rec.dst = '%s,%s' % (rec.model, rec.res_id or 0)
                    rec.dst_name = self.env[rec.model]._description
                except ValueError as e:
                    logger.error('Exten dst error: %s', e)
                    rec.dst = None
                    rec.dst_name = None
            else:
                rec.dst = None
                rec.dst_name = None

    def _set_dst(self):
        for rec in self:
            if rec.dst:
                rec.write({'model': rec.dst._name, 'res_id': rec.dst.id})
                if hasattr(rec.dst, 'exten'):
                    rec.dst.exten = rec
            else:
                rec.write({'model': False, 'res_id': False})

    def _get_twiml(self):
        for rec in self:
            try:
                rec.twiml = pretty_xml(str(rec.dst.render()))
            except Exception as e:
                logger.warning('Cannot render exten: %s', e)
                rec.twiml = 'Render error (normal case with dynamic values)'

    def render(self, request={}, params={}):
        self.ensure_one()
        if not self.dst:
            response = VoiceResponse()
            response.say('Extension not configured!')
            return response
        params['ExtenID'] = self.id
        params['ExtenNumber'] = self.number
        return self.dst.render(request=request, params=params)

    @api.model
    def create_extension(self, rec, ext_type):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'connect.exten',
            'view_mode': 'form',
            'res_id': rec.exten.id if rec.exten else False,
            'target': 'new' if not rec.exten else 'current',
            'context': {
                'default_dst': 'connect.{},{}'.format(ext_type, rec.id)
            }
        }
