import logging
from odoo import api
from odoo.api import SUPERUSER_ID
from odoo.tools.sql import rename_column

logger = logging.getLogger(__name__)

def migrate(cr, version):
    print('Migrating to Webhook User...')
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.users'].search([('login', '=', 'connect')]).unlink()

