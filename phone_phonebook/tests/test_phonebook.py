# -*- coding: utf-8 -*-
from unittest.mock import patch
from xml.etree import ElementTree as ET

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tools import human_size

from odoo.addons.phone_phonebook.models.res_partner import ResPartner


@tagged('post_install', '-at_install')
class TestYealinkPhonebook(HttpCase):

    def setUp(self):
        super().setUp()
        self.token = 'test-phonebook-token'
        self.env['ir.config_parameter'].sudo().set_param(
            'phone_phonebook.token', self.token)
        self.partner = self.env['res.partner'].create({
            'name': 'Phonebook Test Partner',
            'phone': '+1 (555) 010-4242',
        })

    def _fetch_names(self):
        response = self.url_open(
            '/phonebook/yealink.xml?token=%s' % self.token)
        self.assertEqual(response.status_code, 200)
        root = ET.fromstring(response.content)
        self.assertEqual(root.tag, 'YealinkIPPhoneDirectory')
        return {
            entry.findtext('Name'): [t.text for t in entry.findall('Telephone')]
            for entry in root.findall('DirectoryEntry')
        }

    def test_rejects_missing_or_bad_token(self):
        self.assertEqual(
            self.url_open('/phonebook/yealink.xml').status_code, 403)
        self.assertEqual(
            self.url_open('/phonebook/yealink.xml?token=wrong').status_code, 403)

    def test_unknown_brand(self):
        # Token is checked before the format is disclosed.
        self.assertEqual(
            self.url_open('/phonebook/nosuchphone.xml').status_code, 403)
        self.assertEqual(
            self.url_open('/phonebook/nosuchphone.xml?token=%s'
                          % self.token).status_code, 404)

    def test_serves_directory_xml(self):
        entries = self._fetch_names()
        self.assertIn('Phonebook Test Partner', entries)
        # Formatting characters are stripped down to a dialable string.
        self.assertEqual(entries['Phonebook Test Partner'], ['+15550104242'])

    def test_skips_number_named_partners(self):
        self.env['res.partner'].create([
            {'name': '+1 555 000 1111', 'phone': '+1 555 000 1111'},
            {'name': '?', 'phone': '+1 555 000 2222'},
        ])
        names = self._fetch_names()
        self.assertNotIn('+1 555 000 1111', names)
        self.assertNotIn('?', names)
        self.assertIn('Phonebook Test Partner', names)

    def test_recent_caller_filter(self):
        self.env['res.partner'].create({
            'name': 'Stale Caller',
            'phone': '+1 555 010 9999',
        })
        with patch.object(ResPartner, '_phonebook_recent_caller_ids',
                          return_value=[self.partner.id]):
            names = self._fetch_names()
        self.assertIn('Phonebook Test Partner', names)
        self.assertNotIn('Stale Caller', names)

    def test_filter_inactive_without_connect(self):
        # connect.call is not in this registry: months param must be ignored
        # and every contact with a number served.
        self.env['ir.config_parameter'].sudo().set_param(
            'phone_phonebook.recent_call_months', '6')
        self.assertIn('Phonebook Test Partner', self._fetch_names())

    def test_extra_domain_filters_contacts(self):
        self.env['res.partner'].create({
            'name': 'Filtered Out',
            'phone': '+1 555 010 8888',
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'phone_phonebook.extra_domain', "[('name', '!=', 'Filtered Out')]")
        names = self._fetch_names()
        self.assertIn('Phonebook Test Partner', names)
        self.assertNotIn('Filtered Out', names)

    def test_broken_saved_domain_is_ignored(self):
        # A filter that turns invalid after saving (e.g. field removed)
        # must not take the phones down.
        self.env['ir.config_parameter'].sudo().set_param(
            'phone_phonebook.extra_domain', "[('gone_field', '=', 1)]")
        self.assertIn('Phonebook Test Partner', self._fetch_names())

    def test_settings_domain_validation(self):
        Settings = self.env['res.config.settings']
        for bad in ('not a domain', "[('no_such_field', '=', 1)]", '{"a": 1}'):
            settings = Settings.create({'phone_phonebook_extra_domain': bad})
            with self.assertRaises(ValidationError):
                settings.set_values()
        good = Settings.create({
            'phone_phonebook_extra_domain': "[('name', '!=', False)]"})
        good.set_values()
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param(
                'phone_phonebook.extra_domain'),
            "[('name', '!=', False)]")

    def test_stats_match_directory(self):
        settings = self.env['res.config.settings'].create({})
        response = self.url_open(
            '/phonebook/yealink.xml?token=%s' % self.token)
        root = ET.fromstring(response.content)
        count = len(root.findall('DirectoryEntry'))
        self.assertIn('%s entries' % count, settings.phone_phonebook_stats)
        self.assertIn(human_size(len(response.content)),
                      settings.phone_phonebook_stats)
        # connect is not installed here: the window must read as "all".
        self.assertIn('all contacts', settings.phone_phonebook_stats)
