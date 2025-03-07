# -*- coding: utf-8 -*-

import logging
import phonenumbers
import re
from phonenumbers import phonenumberutil
from odoo import models, fields, api, release
from .settings import debug

logger = logging.getLogger(__name__)

def strip_number(number):
    """Strip number formating"""
    if not isinstance(number, str):
        return number
    pattern = r'[\s\(\)\-\+]'
    return re.sub(pattern, '', number).lstrip('0')


def format_number(self, number, country=None, format_type='e164'):
    """Return number in requested format_type
    """
    res = False
    try:
        phone_nbr = phonenumbers.parse(number, country)
        if not phonenumbers.is_possible_number(phone_nbr):
            debug(self, '{} country {} parse impossible'.format(
                number, country
            ))
        # We have a parsed number, let check what format to return.
        elif format_type == 'e164':
            res = phonenumbers.format_number(
                phone_nbr, phonenumbers.PhoneNumberFormat.E164)
        else:
            logger.error('WRONG FORMATTING PASSED: %s', format_type)
    except phonenumberutil.NumberParseException:
        debug(self, '{} {} {} got NumberParseException'.format(
            number, country, format_type
        ))
    except Exception:
        logger.exception('FORMAT NUMBER ERROR: ')
    finally:
        debug(self, '{} county {} format {}: {}'.format(
            number, country, format_type, res))
        return res or number



class Partner(models.Model):
    _inherit = 'res.partner'

    connect_calls_count = fields.Integer(compute='_get_connect_calls_count')
    connect_recorded_calls = fields.One2many('connect.recording', 'partner')
    twlidoo_phone_normalized = fields.Char(compute='_get_twlidoo_phone_normalized',
                                   index=True, store=True,
                                   string='E.164 phone')
    twlidoo_mobile_normalized = fields.Char(compute='_get_twlidoo_phone_normalized',
                                    index=True, store=True,
                                    string='E.164 mobile')


    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        try:
            if self.env.context.get('connect_call_id'):
                call = self.env['connect.call'].sudo().browse(
                    self.env.context['connect_call_id'])
                call.partner = res[0]
        except Exception as e:
            logger.exception(e)
        if res and not self.env.context.get('no_clear_cache'):
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return res

    def write(self, values):
        res = super().write(values)
        if res and not self.env.context.get('no_clear_cache'):
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return res

    def unlink(self):
        res = super().unlink()
        if res and not self.env.context.get('no_clear_cache'):
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return res


    @api.depends('phone', 'mobile', 'country_id')
    def _get_twlidoo_phone_normalized(self):
        for rec in self:
            rec.update({
                'twlidoo_phone_normalized': rec._normalize_phone(rec.phone) if rec.phone else False,
                'twlidoo_mobile_normalized': rec._normalize_phone(rec.mobile) if rec.mobile else False
            })

    def _normalize_phone(self, number):
        """Keep normalized (E.164) phone numbers in normalized fields.
        """
        if self.env['connect.settings'].sudo().get_param('disable_phone_format'):
            return number
        country = self._get_country()
        try:
            phone_nbr = phonenumbers.parse(number, country)
            if phonenumbers.is_possible_number(phone_nbr) or \
                    phonenumbers.is_valid_number(phone_nbr):
                number = phonenumbers.format_number(
                    phone_nbr, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.phonenumberutil.NumberParseException:
            # Force the number to be E.164 format.
            number = '+{}'.format(strip_number(number))
        except Exception as e:
            logger.warning('Normalize phone error: %s', e)
        # Strip the number if parse error.
        return number


    @api.model
    def get_partner_by_number(self, number):
        """Search partner by number.
        Args:
            number (str): number to be searched on.
        If several partners are found by the same number:
        a) If partners belong to same company, return company record.
        b) If partners belong to different companies return False.
        """
        re_uri = re.compile(r'^sip:(\+\d+)@(.+)$')
        found = re_uri.search(number)
        if found:
            number = found.group(1)
        found = self.sudo().search([
            '|',
            ('twlidoo_phone_normalized', '=', number),
            ('twlidoo_mobile_normalized', '=', number)])
        debug(self, '{} belongs to partners: {}'.format(
            number, found.mapped('id')
        ))
        parents = found.mapped('parent_id')
        # 1-st case: just one partner, perfect!
        if len(found) == 1:
            return found
        # 2-nd case: Many partners, no parent company / many companies
        elif len(parents) == 0 and len(found) > 1:
            logger.warning('MANY PARTNERS FOR NUMBER %s', number)
            return found[0]
        # 3-rd case: many partners, many companies
        elif len(parents) > 1 and len(found) > 1:
            logger.warning(
                'MANY PARTNERS DIFFERENT COMPANIES FOR NUMBER %s', number)
            # Return empty recordset.
            return self.env['res.partner']
        # 4-rd case: 1 partner from one company
        elif len(parents) == 1 and len(found) == 2 and len(
                found.filtered(
                    lambda r: r.parent_id.id in [k.id for k in parents])) == 1:
            debug(self, 'one partner from one parent found')
            return found.filtered(
                lambda r: r.parent_id in [k for k in parents])[0]
        # 5-rd case: many partners same parent company
        elif len(parents) == 1 and len(found) > 1 and len(found.filtered(
                lambda r: r.parent_id in [k for k in parents])) > 1:
            debug(self, 'MANY PARTNERS SAME PARENT COMPANY {}'.format(number))
            return parents[0]
        else:
            # Return empty recordset.
            return self.env['res.partner']

    def _get_country(self):
        partner = self
        if partner and partner.country_id:
            # Return partner country code
            return partner.country_id.code
        elif partner and partner.parent_id and partner.parent_id.country_id:
            # Return partner's parent country code
            return partner.parent_id.country_id.code
        elif partner and partner.company_id and partner.company_id.country_id:
            # Return partner's company country code
            return partner.company_id.country_id.code
        elif self.env.user and self.env.user.company_id.country_id:
            # Return Odoo's main company country
            return self.env.user.company_id.country_id.code

    def _get_connect_calls_count(self):
        for rec in self:
            if rec.is_company:
                rec.connect_calls_count = self.env[
                    'connect.call'].sudo().search_count(
                    ['|', ('partner', '=', rec.id),
                          ('partner.parent_id', '=', rec.id)])
            else:
                rec.connect_calls_count = self.env[
                    'connect.call'].sudo().search_count(
                    [('partner', '=', rec.id)])

    def _phone_format(self, number=None, country=None, company=None, force_format='E164', **kwargs):
        version_info = release.version_info
        # For Odoo versions before 16
        if version_info[0] < 16:
            return super(Partner, self)._phone_format(number, country=country, company=company)
        # For Odoo version 16
        elif version_info[0] == 16:
            return super(Partner, self)._phone_format(number, country=country, company=company, force_format=force_format)
        # For Odoo version 17 and later
        else:
            # Ensure 'fname' and 'raise_exception' are extracted from kwargs or set to defaults
            fname = kwargs.get('fname', False)
            raise_exception = kwargs.get('raise_exception', False)
            return super(Partner, self)._phone_format(fname=fname, number=number, country=country, force_format=force_format, raise_exception=raise_exception)

    @api.model
    def api_get_partner(self, number):
        # Called from Client.
        partner = self.get_partner_by_number(number)
        if partner:
            return {'id': partner.id, 'name': partner.display_name}
        else:
            return {'id': False, 'name': 'Unknown'}

