# -*- coding: utf-8 -*-
import logging
import re
from xml.etree import ElementTree as ET

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.tools import safe_eval

logger = logging.getLogger(__name__)

# Characters a phone can dial; everything else is display formatting.
NON_DIALABLE = re.compile(r'[^0-9+*#]')

DEFAULT_RECENT_CALL_MONTHS = 6


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _phonebook_int_param(self, name, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(
                name, default))
        except (TypeError, ValueError):
            return default

    @api.model
    def _phonebook_eval_context(self):
        """Evaluation context for the custom filter, matching what the
        domain widget may emit for relative dates."""
        return {
            'datetime': safe_eval.datetime,
            'dateutil': safe_eval.dateutil,
            'time': safe_eval.time,
            'context_today': fields.Date.today,
            'uid': self.env.uid,
            'user': self.env.user,
        }

    @api.model
    def _phonebook_extra_domain(self, value=None):
        """Evaluate the custom contact filter (the saved one when no raw
        value is passed). Returns [] when unset; raises on invalid input."""
        if value is None:
            value = self.env['ir.config_parameter'].sudo().get_param(
                'phone_phonebook.extra_domain') or ''
        value = value.strip()
        if not value or value == '[]':
            return []
        domain = safe_eval.safe_eval(value, self._phonebook_eval_context())
        if not isinstance(domain, list):
            raise ValueError('a domain must be a list, got %r' % (domain,))
        return domain

    @api.model
    def _phonebook_active_months(self):
        """The recent-calls window in months, 0 when the filter is off
        (disabled in settings or Connect not installed)."""
        months = self._phonebook_int_param(
            'phone_phonebook.recent_call_months', DEFAULT_RECENT_CALL_MONTHS)
        if months <= 0 or 'connect.call' not in self.env:
            return 0
        return months

    @api.model
    def _phonebook_recent_caller_ids(self):
        """Ids of partners involved in an incoming or outgoing call within
        the configured window, or None when the filter is disabled (months
        set to 0) or the Connect telephony module is not installed — None
        means "serve all".
        """
        months = self._phonebook_active_months()
        if not months:
            return None
        cutoff = fields.Datetime.now() - relativedelta(months=months)
        groups = self.env['connect.call'].sudo()._read_group(
            [
                ('direction', 'in', ('incoming', 'outgoing')),
                ('partner', '!=', False),
                ('create_date', '>=', cutoff),
            ],
            ['partner'],
        )
        return [partner.id for (partner,) in groups]

    @api.model
    def _phonebook_number_fields(self):
        # res.partner lost "mobile" in recent versions; keep both paths working.
        return [f for f in ('phone', 'mobile') if f in self._fields]

    @api.model
    def _phonebook_domain(self, include_extra=True):
        number_fields = self._phonebook_number_fields()
        domain = ['|'] * (len(number_fields) - 1) + [
            (field, '!=', False) for field in number_fields]
        recent_ids = self._phonebook_recent_caller_ids()
        if recent_ids is not None:
            domain = [('id', 'in', recent_ids)] + domain
        if include_extra:
            domain = self._phonebook_extra_domain() + domain
        return domain

    @api.model
    def _phonebook_entries(self):
        """The served directory, brand-neutral: a list of dicts with 'name'
        and 'numbers' keys. Renderers may rely on extra keys being added
        here when a format needs them (e.g. split first/last names).
        """
        number_fields = self._phonebook_number_fields()
        read_fields = ['display_name'] + number_fields
        try:
            partners = self.sudo().search_read(
                self._phonebook_domain(), read_fields)
        except Exception:
            # The custom filter is validated on save; if it breaks later
            # (e.g. a field it uses was removed), keep serving the phones.
            logger.exception(
                'Ignoring invalid phone_phonebook.extra_domain filter')
            partners = self.sudo().search_read(
                self._phonebook_domain(include_extra=False), read_fields)
        entries = []
        for partner in partners:
            numbers = []
            for field in number_fields:
                number = NON_DIALABLE.sub('', partner.get(field) or '')
                if number and number not in numbers:
                    numbers.append(number)
            name = partner['display_name'] or ''
            # Auto-created partners for unknown callers are named after the
            # number itself (or "?"); they add nothing over the number.
            if not numbers or not any(c.isalpha() for c in name):
                continue
            entries.append({'name': name, 'numbers': numbers})
        return entries

    @api.model
    def _phonebook_render(self, brand):
        """Render the directory for a phone brand, or None when no renderer
        exists for it. Adding a brand = adding a _phonebook_render_<brand>
        method; the URL /phonebook/<brand>.xml starts working with it.
        """
        if not brand.isalnum():
            return None
        renderer = getattr(self, '_phonebook_render_%s' % brand.lower(), None)
        return renderer() if renderer is not None else None

    @api.model
    def _phonebook_render_yealink(self, entries=None):
        """YealinkIPPhoneDirectory XML bytes (also fits Yealink-compatible
        firmwares)."""
        if entries is None:
            entries = self._phonebook_entries()
        root = ET.Element('YealinkIPPhoneDirectory')
        for values in entries:
            entry = ET.SubElement(root, 'DirectoryEntry')
            ET.SubElement(entry, 'Name').text = values['name']
            # A Yealink DirectoryEntry holds at most 3 numbers.
            for number in values['numbers'][:3]:
                ET.SubElement(entry, 'Telephone').text = number
        return ET.tostring(root, encoding='UTF-8', xml_declaration=True)
