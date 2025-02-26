# -*- coding: utf-8 -*

{
    'name': 'Connect ElevenLabs',
    'version': '1.0.1',
    'author': 'Oduist',
    'price': 0,
    'currency': 'EUR',
    'maintainer': 'Oduist',
    'live_test_url': 'https://connect-demo-18.oduist.com/',
    'support': 'mailbox@connect.com',
    'license': 'Other proprietary',
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
