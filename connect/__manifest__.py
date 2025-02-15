# -*- encoding: utf-8 -*-

{
    'name': 'Connect',
    'version': '0.10',
    'author': 'Odooist',
    'maintainer': 'Odooist',
    'price': 0,
    'currency': 'EUR',
    'support': 'odooist@gmail.com',
    'license': 'Other proprietary',
    'category': 'Phone',
    'summary': 'Twilio and Odoo integration application',
    'description': "",
    'depends': ['mail', 'contacts', 'sms'],
    'external_dependencies': {
        'python': ['twilio', 'openai'],
    },
    'data': [
        'data/res_users.xml',
        'data/data.xml',
        'data/functions.xml',
        'data/ir_cron.xml',
        'data/ref.xml',
        'data/twiml.xml',
        'data/query_prompt.xml',
        'data/outgoing_rules.xml',
        'data/res_partner.xml',
        # Security
        'security/groups.xml',
        'security/admin.xml',
        'security/billing.xml',
        'security/user.xml',
        'security/user_record_rules.xml',
        # Views
        'views/menu.xml',
        'views/settings.xml',
        'views/domain.xml',
        'views/user.xml',
        'views/twiml.xml',
        'views/debug.xml',
        'views/exten.xml',
        'views/byoc.xml',
        'views/call.xml',
        'views/callflow.xml',
        'views/callout.xml',
        'views/channel.xml',
        'views/outgoing_callerid.xml',
        'views/outgoing_rule.xml',
        'views/recording.xml',
        'views/query.xml',
        'views/query_prompt.xml',
        'views/query_source.xml',
        'views/queue.xml',
        'views/number.xml',
        'views/favorite.xml',
        'views/res_partner.xml',
        'views/message.xml',
        # Wizard
        'wizard/add_credits.xml',
        'wizard/cancel_subscription.xml',
        'wizard/transfer.xml',
        'wizard/manage_partner_callout.xml',
        ],
    'demo': [
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': ['static/description/icon.png'],
    'assets': {
        'web.assets_backend': [
            '/connect/static/src/icomoon/style.css',
            '/connect/static/src/components/phone/*/*',
            '/connect/static/src/js/main.js',
            '/connect/static/src/js/utils.js',
            '/connect/static/src/widgets/phone_field/*',
            '/connect/static/src/services/actions/*',
            '/connect/static/src/services/active_calls/*',
            #'/connect/static/src/services/intercom/*',
        ],
    }
}
