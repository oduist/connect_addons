{
    'name': 'Connect Elevenlabs Knowledge',
    'description': """Integrate Elelvenlabs Knowledge""",
    'currency': 'EUR',
    'price': '0',
    'version': '1.0.2',
    'category': 'pHONE',
    'live_test_url': 'https://connect-demo-18.oduist.com/',
    'author': 'Oduist',
    'license': 'Other proprietary',
    'installable': True,
    'application': False,
    'auto_install': False,
    'depends': [ 'connect', 'connect_elevenlabs'],
    'data': [
        # Security
        'security/admin.xml',
        'security/user.xml',
        # Views
        'views/agent.xml',
        'views/knowledge.xml',
        'views/settings.xml',
    ],
    'demo': [],
    'images': ['static/description/logo.png'],
}
