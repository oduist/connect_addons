{
    'name': 'Connect Website',
    'description': """Let's talk. One click call using Twilio""",
    'currency': 'EUR',
    'price': '0',
    'version': '1.0.1',
    'category': 'Website/Website',
    'live_test_url': 'https://connect-demo-18.oduist.com/',
    'author': 'Oduist',
    'license': 'Other proprietary',
    'installable': True,
    'application': False,
    'auto_install': False,
    'depends': ['website', 'connect'],
    'data': [
        # Views
        'views/settings.xml',
        # Snippets
        'views/snippets/s_talk_button.xml',
        'views/snippets/snippets.xml',
    ],
    'demo': [],
    'images': ['static/description/logo.png'],
}
