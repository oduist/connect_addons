from odoo import api
from odoo.api import SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    byocs = env['connect.byoc'].search([])
    if not byocs:
        return
    client = env["connect.settings"].get_client()
    for byoc in byocs:
        try:
            targets = client.voice.v1.connection_policies(byoc.connection_policy_sid).targets.list()
            for target in targets:
                env['connect.byoc_origination_uri'].with_context(skip_twilio_sync=True).create({
                    'byoc': byoc.id,
                    'target': target.target,
                    'sid': target.sid,
                    'priority': target.priority,
                    'weight': target.weight,
                })
        except Exception as e:
            if 'was not found' in str(e):
                pass
            else:
                raise
    print('Connect BYOC migration is done.')