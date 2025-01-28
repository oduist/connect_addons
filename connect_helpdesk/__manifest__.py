# ©️ OdooPBX by Odooist, Odoo Proprietary License v1.0, 2024
# -*- encoding: utf-8 -*-
{
    'name': 'Connect Odoo Helpdesk module',
    'version': '0.1',
    'author': 'Odooist',
    'price': 0,
    'currency': 'EUR',
    'maintainer': 'Odooist',
    'support': 'mailbox@connect.com',
    'license': 'OPL-1',
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
