# -*- coding: utf-8 -*-
{
    'name': 'Remote XML Phonebook',
    'version': '19.0.1.4.1',
    'category': 'Productivity',
    'summary': 'Serve contacts as a remote XML phonebook for Yealink IP phones',
    'description': """
        Exposes Odoo contacts as a Yealink-compatible remote XML phonebook
        (YealinkIPPhoneDirectory format) over HTTP(S).

        Point the phone's Directory -> Remote Phone Book at the URL shown in
        Settings -> Phonebook, or push it via auto-provisioning
        (remote_phonebook.data.1.url). Access is protected by a secret token
        that is generated on install and can be regenerated at any time.
    """,
    'author': 'Mirage Pool Services',
    'license': 'LGPL-3',
    'depends': [
        'base_setup',
        'contacts',
    ],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
