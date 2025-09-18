
# -*- encoding: utf-8 -*-
{
    'name': 'Connect Odoo Helpdesk module',
    'version': '1.0.1',
    'author': 'Oduist',
    'price': 0,
    'currency': 'EUR',
    'maintainer': 'Oduist',
    'support': 'support@oduist.com',
    'license': 'Other proprietary',
    'category': 'Phone',
    'summary': 'Connect Odoo Helpdesk module',
    'description': "",
    'depends': ['helpdesk', 'connect'],
    'data': [
        'views/ticket.xml',
        'views/call.xml',
        'views/settings.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/logo.png'],
    'assets': {
        'web.assets_backend': [
            '/connect_helpdesk/static/src/services/active_calls/*',
        ],
    }
}
