# -*- coding: utf-8 -*-
from . import controllers
from . import models
from . import wizard

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
    try:
        env = _get_env(*args)

        module = env['ir.module.module'].sudo().search([('name', '=', 'connect')], limit=1)

        if module:
            module.sudo().write({'create_date': fields.Datetime.now()})

    except Exception as e:
        _logger.error('Error in post_init_hook: %s', str(e))

    try:
        env['connect.license'].sudo().update_license_status(raise_exc=False)
    except Exception:
        pass
