import logging
from odoo import api, SUPERUSER_ID
from odoo.tools.sql import rename_column

logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Merge defaults.
    for field in ['admin_name', 'admin_phone', 'admin_email', 'web_base_url']:
        default_value = env['connect.settings'].get_param(field)
        if not default_value and field == 'admin_phone':
            default_value = '1234567890'
        elif not default_value and field == 'admin_email':
            default_value = 'admin@example.com'
        env['connect.settings'].set_param(
            field, default_value)
    logger.info('Connect settings migrated.')
    # Sync numbers
    if not env['connect.number'].search([]):
        logger.info('No DID numbers to migrate.')
        return
    # Sync outgoing calleid numbers
    env['connect.outgoing_callerid'].sync()
    # Copy numbers
    for user in env['connect.user'].search([]):
        if user.callerid_number:
            callerid = env['connect.outgoing_callerid'].search([
                ('number', '=', user.callerid_number.phone_number)])
            if callerid:
                user.outgoing_callerid = callerid
                logger.info('CallerId %s for user %s migrated.', callerid.number, user.name)
