# -*- coding: utf-8 -*
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
{
    'name': 'Connect ElevenLabs',
    'version': '0.1',
    'author': 'Odooist',
    'price': 0,
    'currency': 'EUR',
    'maintainer': 'Odooist',
    'support': 'mailbox@connect.com',
    'license': 'OPL-1',
    'category': 'Phone',
    'summary': 'Connect ElevenLabs integration module',
    'description': "",
    'depends': ['connect', 'calendar'],
    'external_dependencies': {
        'python': ['elevenlabs'],
    },
    'data': [
        'security/admin.xml',
        'security/user.xml',
        'views/settings.xml',
        'views/voice.xml',
        'views/callflow.xml',
        'views/callout.xml',
        'views/user.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/logo.png'],
    'assets': {
        'web.assets_backend': [],
    }
}
