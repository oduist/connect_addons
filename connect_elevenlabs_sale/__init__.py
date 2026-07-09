from . import controllers

import logging
from odoo import fields, api
from odoo.api import SUPERUSER_ID

_logger = logging.getLogger(__name__)
def post_init_hook(*args):
    try:
        # Handle different Odoo versions
        if len(args) == 1:
            # Odoo 16+ - single env argument
            env = args[0]
        else:
            # Odoo 15 - cr and registry arguments
            cr, registry = args
            env = api.Environment(cr, SUPERUSER_ID, {})
        # Find the connect_elevenlabs_sale module record
        module = env['ir.module.module'].search([('name', '=', 'connect_elevenlabs_sale')], limit=1)
        if module:
            module.write({'create_date': fields.Datetime.now()})
        # Update module pricing.
        env['oduist.license'].update_license_status(raise_exc=False)
    except Exception as e:
        _logger.error('Error in post_init_hook: %s', str(e))