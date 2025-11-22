import secrets
import string

from . import controllers
from . import models
from . import wizard


def _post_init_hook(env):
    user = env.ref("connect.user_connect_webhook")
    chars = string.ascii_letters + string.digits + string.punctuation
    password = 'X1!x'+''.join(secrets.choice(chars) for _ in range(16))
    user.write({'password': password})
