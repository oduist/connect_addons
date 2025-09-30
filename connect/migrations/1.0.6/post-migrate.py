from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Reset admin name to migrate registration fields.
    env['connect.settings'].set_param('admin_name', '')
    print('Connect app migration is done.')
