# -*- encoding: utf-8 -*-
{
    'name': 'Twilio Odoo CRM integration',
    'version': '0.1',
    'author': 'Oduist',
    'price': 0,
    'currency': 'EUR',
    'maintainer': 'Oduist',
    'support': 'support@oduist.com',
    'license': 'Other proprietary',
    'category': 'Phone',
    'summary': 'Twilio Odoo CRM integration',
    'description': "",
    'depends': ['crm', 'utm', 'connect'],
    'data': [
        'security/webhook.xml',
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
