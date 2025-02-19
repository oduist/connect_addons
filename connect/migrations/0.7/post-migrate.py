from odoo.tools.sql import rename_column
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    print('Assigning partners to recordings from calls...')
    recs = env['connect.recording'].search([])
    for rec in recs:
        if rec.call.partner:
            rec.partner = rec.call.partner
    print('Migration done.')
