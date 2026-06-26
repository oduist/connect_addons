from . import controllers
from . import models
from .hooks import pre_init_hook, relink_orphan_agent_tools

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
        # Find the connect_elevenlabs module record
        module = env['ir.module.module'].search([('name', '=', 'connect_elevenlabs')], limit=1)
        if module:
            module.write({'create_date': fields.Datetime.now()})
        # Update module pricing.
        env['oduist.license'].update_license_status(raise_exc=False)
    except Exception as e:
        _logger.error('Error in post_init_hook: %s', str(e))
