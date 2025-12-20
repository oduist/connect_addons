from . import controllers
from . import models

import logging
from odoo import fields, api, SUPERUSER_ID

_logger = logging.getLogger(__name__)
def post_init_hook(*args):
    """
    Hook called after module installation.
    Updates the create_date field in ir.module.module for trial period calculation.

    Compatible with both Odoo 15 (cr, registry) and Odoo 16+ (env) signatures.
    """
    try:
        # Handle different Odoo versions
        if len(args) == 1:
            # Odoo 16+ - single env argument
            env = args[0]
        else:
            # Odoo 15 - cr and registry arguments
            cr, registry = args
            env = api.Environment(cr, SUPERUSER_ID, {})

        # Find the connect module record
        module = env['ir.module.module'].sudo().search([('name', '=', 'connect_elevenlabs')], limit=1)

        if module:
            # Update create_date to current time to ensure proper trial period calculation
            module.sudo().write({'create_date': fields.Datetime.now()})
            _logger.info('Connect Elevenlabs module installation date updated for trial period')
        else:
            _logger.warning('Connect Elevenlabs module not found in ir.module.module')

    except Exception as e:
        _logger.error('Error in post_init_hook: %s', str(e))
