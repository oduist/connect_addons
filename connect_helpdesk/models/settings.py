# -*- coding: utf-8 -*

from odoo import fields, models
from odoo.addons.connect.models.settings import CONNECT_MODULES

CONNECT_MODULES.append('connect_helpdesk')


class HelpdeskSettings(models.Model):
    _inherit = 'connect.settings'

