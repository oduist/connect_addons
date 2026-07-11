# Connect Memory — base module. Odoo is the event emitter into
# connect.memory.outbox; an external service drives the memory engine and
# writes answers back into connect.memory.inbox.
from . import models
from . import controllers
