from . import agent
from . import agent_tool
from . import agent_template
from . import call
from . import callflow
from . import exten
from . import file
from . import number
from . import settings
from . import user
from . import voice
from . import recording

# Inject documentation page.
from odoo.addons.connect.models.documentation import PAGE_MAP
PAGE_MAP[2] = ['Connect Elevenlabs', 'connect_elevenlabs']

