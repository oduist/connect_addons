# -*- coding: utf-8 -*

{
    'name': 'Connect ElevenLabs',
    'version': '1.0.7',
    'author': 'Oduist',
    'price': 0,
    'currency': 'EUR',
    'maintainer': 'Oduist',
    'live_test_url': 'https://connect-demo-18.oduist.com/',
    'support': 'support@oduist.com',
    'license': 'Other proprietary',
    'category': 'Phone',
    'summary': 'Connect ElevenLabs integration module',
    'description': "",
    'depends': ['connect', 'calendar'],
    'external_dependencies': {
        'python': ['elevenlabs'],
    },
    'data': [
        # Data
        'data/tools.xml',
        'data/agent_templates.xml',
        'data/sip_trunk.xml',
        # Security
        'security/admin.xml',
        'security/user.xml',
        'security/webhook.xml',
        # Views
        'views/call.xml',
        'views/settings.xml',
        'views/voice.xml',
        'views/callflow.xml',
        'views/user.xml',
        'views/agent.xml',
        'views/agent_prompt.xml',
        'views/agent_transfer.xml',
        'views/agent_template.xml',
        'views/agent_tool.xml',
        'views/agent_tool_params.xml',
        'views/number.xml',
        'views/recording.xml',
        'views/documentation.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': ['static/description/logo.png'],
    'assets': {
        'web.assets_backend': [],
    },
    'post_init_hook': 'post_init_hook',
}
