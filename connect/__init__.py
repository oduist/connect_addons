# -*- coding: utf-8 -*-
import logging
from odoo import fields, api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def _get_env(*args):
    """Get environment from hook arguments (compatible with Odoo 15 and 16+)."""
    if len(args) == 1:
        return args[0]
    else:
        cr, registry = args
        return api.Environment(cr, SUPERUSER_ID, {})


def post_init_hook(*args):
    """
    Hook called after module installation.
    Updates the create_date field in ir.module.module for trial period calculation.
    Also attempts to fetch license data from the server.
    
    Compatible with both Odoo 15 (cr, registry) and Odoo 16+ (env) signatures.
    """
    try:
        env = _get_env(*args)
        
        module = env['ir.module.module'].sudo().search([('name', '=', 'connect')], limit=1)
        
        if module:
            module.sudo().write({'create_date': fields.Datetime.now()})
        
    except Exception as e:
        _logger.error('Error in post_init_hook: %s', str(e))

    try:
        env['connect.license'].sudo().update_license_status()
        _logger.info('License status updated after installation')
    except Exception as e:
        _logger.debug('License status update skipped: %s', str(e))


from . import controllers
from . import models
from . import wizard
