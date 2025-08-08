from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for user in env['connect.user'].search([]):
        # Reset SIP
        if user.sip_enabled:
            user.sip_enabled = False
            user.sip_enabled = True
        # Reset Client
        if user.client_enabled:
            user.client_enabled = False
            user.client_enabled = True
        # Reset Voicemail
        if user.voicemail_enabled:
            user.voicemail_enabled = False
            user.voicemail_enabled = True
    print('Connect app migration is done.')