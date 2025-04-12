import logging

from . import controllers
from . import models
from . import wizard

from odoo import api, SUPERUSER_ID, tools, release

logger = logging.getLogger(__name__)


