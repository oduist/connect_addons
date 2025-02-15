{
    'name': 'Connect Website',
    'description': """Let's talk. One click call using Twilio""",
    'currency': 'EUR',
    'price': '100',
    'version': '1.0',
    'category': 'Website/Website',
    'author': 'Odooist',
    'license': 'OPL-1',
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
