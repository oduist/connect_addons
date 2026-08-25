# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import human_size


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    phone_phonebook_token = fields.Char(
        string='Phonebook Access Token',
        config_parameter='phone_phonebook.token',
        readonly=True,
    )
    phone_phonebook_recent_call_months = fields.Integer(
        string='Recent Callers Only (Months)',
        config_parameter='phone_phonebook.recent_call_months',
        default=6,
    )
    phone_phonebook_extra_domain = fields.Char(
        string='Phonebook Contact Filter',
        config_parameter='phone_phonebook.extra_domain',
        default='[]',
    )
    phone_phonebook_url = fields.Char(
        string='Phonebook URL',
        compute='_compute_phone_phonebook_url',
    )
    phone_phonebook_stats = fields.Char(
        string='Served Directory',
        compute='_compute_phone_phonebook_stats',
    )

    @api.depends('phone_phonebook_token')
    def _compute_phone_phonebook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '')
        for settings in self:
            settings.phone_phonebook_url = '%s/phonebook/yealink.xml?token=%s' % (
                base_url, settings.phone_phonebook_token or '<token>')

    def _compute_phone_phonebook_stats(self):
        # Reflects the saved configuration (recompute after saving changes).
        Partner = self.env['res.partner']
        entries = Partner._phonebook_entries()
        size_bytes = len(Partner._phonebook_render_yealink(entries))
        months = Partner._phonebook_active_months()
        if months:
            window = _('contacts with calls in the last %s months', months)
        else:
            window = _('all contacts with a phone number')
        stats = _('%(count)s entries, %(size)s (%(window)s)',
                  count=len(entries), size=human_size(size_bytes),
                  window=window)
        if size_bytes > 1_500_000:
            stats += _(' — over the 1.5 M limit!')
        for settings in self:
            settings.phone_phonebook_stats = stats

    def set_values(self):
        self._validate_phone_phonebook_domain()
        super().set_values()

    def _validate_phone_phonebook_domain(self):
        Partner = self.env['res.partner']
        for settings in self:
            try:
                domain = Partner._phonebook_extra_domain(
                    settings.phone_phonebook_extra_domain or '')
                Partner.search(domain, limit=1)
            except Exception as e:
                raise ValidationError(
                    _('Invalid phonebook contact filter: %s', e)) from e

    def action_regenerate_phonebook_token(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'phone_phonebook.token', secrets.token_urlsafe(24))
        return {'type': 'ir.actions.client', 'tag': 'reload'}
