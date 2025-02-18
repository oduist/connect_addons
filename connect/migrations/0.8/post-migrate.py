from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Reset subscription
    env['connect.settings'].set_param('is_registered', False)
    env['connect.settings'].set_param('is_subscribed', False)
    # Remove API URL is it's based on the region now.
    env['ir.config_parameter'].search([('key', '=', 'connect.api_url')]).unlink()
    # Reset the key for new subscription process.
    env['ir.config_parameter'].search([('key', '=', 'connect.api_key')]).unlink()
    settings = env['connect.settings'].search([], limit=1)
    protected_fields = ['auth_token', 'twilio_api_secret', 'openai_api_key']
    for field_name in protected_fields:
        if settings.get_param(field_name):
            settings.set_param('display_{}'.format(field_name), settings.get_param(field_name))
    print('Migration done.')
