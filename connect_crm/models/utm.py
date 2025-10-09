import logging
from odoo import models, fields, api, release
from odoo.exceptions import ValidationError
from odoo.models import Constraint


logger = logging.getLogger(__name__)


class CallSource(models.Model):
    _inherit = 'utm.source'

    phone = fields.Char()

    # Use modern constraint syntax for Odoo 19, fallback to legacy for older versions
    if release.version_info[0] >= 19:
        _phone_uniq = Constraint('UNIQUE(phone)', 'This phone number is already used!')
    else:
        _sql_constraints = [('phone_uniq', 'UNIQUE(phone)', 'This phone number is already used!')]

