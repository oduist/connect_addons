import logging

from . import controllers
from . import models
from . import wizard

from odoo import api, SUPERUSER_ID, tools, release

logger = logging.getLogger(__name__)


def pre_init_hook(env):
    if release.version_info[0] < 17.0:
        env = api.Environment(env, SUPERUSER_ID, {})
    logger.info('Migrate To Connect')
    query_twilidoo = '''ALTER TABLE twilidoo_call RENAME TO connect_call;
ALTER TABLE twilidoo_twiml RENAME TO connect_twiml;
ALTER TABLE twilidoo_byoc RENAME TO connect_byoc;
ALTER TABLE twilidoo_call_twilidoo_user_rel RENAME TO connect_call_connect_user_rel;
ALTER TABLE res_users_twilidoo_call_rel RENAME TO res_users_connect_call_rel;
ALTER TABLE twilidoo_exten RENAME TO connect_exten;
ALTER TABLE twilidoo_callflow_choice RENAME TO connect_callflow_choice;
ALTER TABLE twilidoo_callflow_twilidoo_user_rel RENAME TO connect_callflow_connect_user_rel;
ALTER TABLE twilidoo_callflow RENAME TO connect_callflow;
ALTER TABLE twilidoo_callout RENAME TO connect_callout;
ALTER TABLE twilidoo_user RENAME TO connect_user;
ALTER TABLE twilidoo_callout_log RENAME TO connect_callout_log;
ALTER TABLE twilidoo_callout_choice RENAME TO connect_callout_choice;
ALTER TABLE twilidoo_callout_contact RENAME TO connect_callout_contact;
ALTER TABLE twilidoo_number RENAME TO connect_number;
ALTER TABLE twilidoo_outgoing_callerid RENAME TO connect_outgoing_callerid;
ALTER TABLE twilidoo_channel RENAME TO connect_channel;
ALTER TABLE twilidoo_debug RENAME TO connect_debug;
ALTER TABLE twilidoo_domain RENAME TO connect_domain;
ALTER TABLE twilidoo_favorite RENAME TO connect_favorite;
ALTER TABLE twilidoo_message RENAME TO connect_message;
ALTER TABLE twilidoo_queue RENAME TO connect_queue;
ALTER TABLE twilidoo_query RENAME TO connect_query;
ALTER TABLE twilidoo_query_twilidoo_query_source_rel RENAME TO connect_query_connect_query_source_rel;
ALTER TABLE twilidoo_query_source RENAME TO connect_query_source;
ALTER TABLE twilidoo_query_prompt RENAME TO connect_query_prompt;
ALTER TABLE twilidoo_queue_twilidoo_user_rel RENAME TO connect_queue_connect_user_rel;
ALTER TABLE twilidoo_outgoing_rule RENAME TO connect_outgoing_rule;
ALTER TABLE twilidoo_transcription_rule RENAME TO connect_transcription_rule;
ALTER TABLE twilidoo_recording RENAME TO connect_recording;
ALTER TABLE twilidoo_cancel_subscription_wizard RENAME TO connect_cancel_subscription_wizard;
ALTER TABLE twilidoo_transfer_wizard RENAME TO connect_transfer_wizard;
ALTER TABLE twilidoo_manage_partner_callout_wizard RENAME TO connect_manage_partner_callout_wizard;
ALTER TABLE twilidoo_callout_twilidoo_manage_partner_callout_wizard_rel RENAME TO connect_callout_connect_manage_partner_callout_wizard_rel;
ALTER TABLE twilidoo_add_credits_wizard RENAME TO connect_add_credits_wizard;
ALTER TABLE twilidoo_settings RENAME TO connect_settings;
ALTER TABLE twilidoo_elevenlabs_file RENAME TO connect_elevenlabs_file;
ALTER TABLE twilidoo_elevenlabs_voice RENAME TO connect_elevenlabs_voice;

ALTER TABLE connect_call_connect_user_rel
RENAME COLUMN twilidoo_call_id to connect_call_id;
ALTER TABLE connect_call_connect_user_rel
RENAME COLUMN twilidoo_user_id to connect_user_id;

ALTER TABLE connect_callflow_connect_user_rel
RENAME COLUMN twilidoo_callflow_id to connect_callflow_id;
ALTER TABLE connect_callflow_connect_user_rel
RENAME COLUMN twilidoo_user_id to connect_user_id;

ALTER TABLE connect_callout_connect_manage_partner_callout_wizard_rel
RENAME COLUMN twilidoo_manage_partner_callout_wizard_id to connect_manage_partner_callout_wizard_id;
ALTER TABLE connect_callout_connect_manage_partner_callout_wizard_rel
RENAME COLUMN twilidoo_callout_id to connect_callout_id;

ALTER TABLE connect_query_connect_query_source_rel
RENAME COLUMN twilidoo_query_id to connect_query_id;
ALTER TABLE connect_query_connect_query_source_rel
RENAME COLUMN twilidoo_query_source_id to connect_query_source_id;

ALTER TABLE connect_queue_connect_user_rel
RENAME COLUMN twilidoo_queue_id to connect_queue_id;
ALTER TABLE connect_queue_connect_user_rel
RENAME COLUMN twilidoo_user_id to connect_user_id;

UPDATE ir_config_parameter
SET key = REPLACE(key, 'twilidoo', 'connect')
WHERE key LIKE '%twilidoo%';
'''

    query_twilidoo_website = '''ALTER TABLE connect_settings 
RENAME COLUMN twilidoo_website_connect_extension to connect_website_connect_extension;
ALTER TABLE connect_settings 
RENAME COLUMN twilidoo_website_connect_domain to connect_website_connect_domain;
ALTER TABLE connect_settings 
RENAME COLUMN twilidoo_website_enable to connect_website_enable;
'''
    try:
        twilidoo = env['ir.module.module'].search([('name', '=', 'twilidoo')])
        if twilidoo.state == 'installed':
            env.cr.execute(query_twilidoo)

        twilidoo_website = env['ir.module.module'].search([('name', '=', 'twilidoo_website')])
        if twilidoo_website.state == 'installed':
            env.cr.execute(query_twilidoo_website)
    except Exception as e:
        logger.warning('Migration exception: ', e)
