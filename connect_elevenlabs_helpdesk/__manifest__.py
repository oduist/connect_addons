# -*- encoding: utf-8 -*-

{
    'name': 'Connect Elevenlabs Helpdesk',
    'version': '1.0.1',
    'author': 'Oduist',
    'maintainer': 'Oduist',
    'live_test_url': 'https://connect-demo-18.oduist.com/',
    'price': 999,
    'currency': 'EUR',
    'support': 'support@oduist.com',
    'license': 'Other proprietary',
    'category': 'Phone',
    'summary': 'AI Helpdesk Ticket Management',
    'description': "AI Helpdesk Ticket Management via Elevenlabs Voice AI",
    "depends": ['connect_elevenlabs', 'connect_helpdesk'],
    'data': [
        'data/tools.xml',
        'data/agent_templates.xml',
    ],
    'demo': [
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/logo.png'],
}
