# -*- encoding: utf-8 -*-

{
    'name': 'Connect Elevenlabs Sale',
    'version': '1.0.0',
    'author': 'Oduist',
    'maintainer': 'Oduist',
    'live_test_url': 'https://connect-demo-18.oduist.com/',
    'price': 999,
    'currency': 'EUR',
    'support': 'support@oduist.com',
    'license': 'Other proprietary',
    'category': 'Phone',
    'summary': 'AI Sale Management',
    'description': "AI Sale Management",
    "depends": ['connect_elevenlabs', 'sale_management'],
    'data': [
        'data/tools.xml',
    ],
    'demo': [
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/logo.png'],
    'post_init_hook': 'post_init_hook',
}

