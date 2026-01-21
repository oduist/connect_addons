# -*- coding: utf-8 -*

from odoo import fields, models
from odoo.addons.connect.models.license import ODUIST_MODULES

ODUIST_MODULES.append('connect_helpdesk')


class HelpdeskSettings(models.Model):
    _inherit = 'connect.settings'

