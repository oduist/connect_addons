# -*- coding: utf-8 -*-
import secrets

from . import controllers
from . import models


def post_init_hook(env):
    """Generate the phonebook access token on first install."""
    icp = env['ir.config_parameter'].sudo()
    if not icp.get_param('phone_phonebook.token'):
        icp.set_param('phone_phonebook.token', secrets.token_urlsafe(24))
