# -*- coding: utf-8 -*-
import logging
from odoo.addons.connect.models.settings import CONNECT_MODULES
from odoo import fields, models

CONNECT_MODULES.append('connect_website')

logger = logging.getLogger(__name__)


class Settings(models.Model):
    _inherit = 'connect.settings'

    connect_website_enable = fields.Boolean(string="Talk Button Enable")
    # Restrict deleting an extension that is used here.
    connect_website_connect_extension = fields.Many2one(
        'connect.exten', string='Connect Extension', ondelete='restrict')
    # Allow to clear the settings when deleting domain. It's an extra rare operation and user knows what is doing.
    connect_website_connect_domain = fields.Many2one(
        'connect.domain', string='Connect Domain', ondelete='set null')
