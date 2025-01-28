# ©️ OdooPBX by Odooist, Odoo Proprietary License v1.0, 2024
# -*- encoding: utf-8 -*-
{
    'name': 'Twilio Odoo CRM integration',
    'version': '0.1',
    'author': 'Odooist',
    'price': 0,
    'currency': 'EUR',
    'maintainer': 'Odooist',
    'support': 'odooist@gmail.com',
    'license': 'OPL-1',
    'category': 'Phone',
    'summary': 'Twilio Odoo CRM integration',
    'description': "",
    'depends': ['crm', 'utm', 'connect'],
    'data': [
        'security/billing.xml',
        'views/crm_lead.xml',
        'views/call.xml',
        'views/utm.xml',
        'views/settings.xml',

    ],
    'demo': [],
    "qweb": ['static/src/xml/*.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/logo.png'],
    'assets': {
        'web.assets_backend': [
            '/connect_crm/static/src/services/active_calls/*',
        ],
    }
}
