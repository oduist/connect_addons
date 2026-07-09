# -*- coding: utf-8 -*

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from werkzeug.exceptions import Unauthorized

from odoo import http

logger = logging.getLogger(__name__)


class CalendarController(http.Controller):

    def check_tool_token(self):
        token = http.request.httprequest.headers.get('x-elevenlabs-agent-token')
        if not token:
            logger.warning('Tool token check failed: no x-elevenlabs-agent-token header in request')
            return False
        expected_token = http.request.env['connect.settings'].sudo().get_param('elevenlabs_agent_token')
        if not expected_token:
            logger.warning('Tool token check failed: elevenlabs_agent_token is not configured in settings')
            return False
        if token != expected_token:
            logger.warning('Tool token check failed: token mismatch (received %s...)', token[:8])
            return False
        logger.info('Tool token check passed')
        return True

    @http.route('/connect_elevenlabs/get_available_slots', methods=['POST'], type='http', auth='public',
                csrf=False)
    def get_available_slots(self):
        logger.info('Incoming request: /connect_elevenlabs/get_available_slots')
        if not self.check_tool_token():
            raise Unauthorized()
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        user_id = kwargs.get('user_id')
        if kwargs.get('timezone'):
            tz_val = kwargs['timezone']
            try:
                user_timezone = ZoneInfo(tz_val)
            except (KeyError, ValueError):
                user_timezone = timezone(timedelta(hours=int(tz_val)))
        else:
            user = http.request.env['res.users'].sudo().browse(user_id)
            tz = user.partner_id.tz
            if not tz:
                tz = 'UTC'
            user_timezone = ZoneInfo(tz)
        if kwargs.get('start'):
            date = datetime.strptime(kwargs.get('start'), '%Y-%m-%d').replace(tzinfo=user_timezone)
        else:
            current_date = datetime.now().date() + timedelta(days=1)
            date = datetime.combine(current_date, datetime.min.time()).replace(tzinfo=user_timezone)
        date = date.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

        end_date = date + timedelta(days=1)

        events = http.request.env['calendar.event'].sudo().search(
            [('user_id', '=', user_id), ('start', '>', date), ('start', '<', end_date)], order='start asc').read(
            ['name', 'start', 'stop'])

        day_start = "{} 08:00:00".format(date.date())
        day_end = "{} 18:00:00".format(date.date())

        free_intervals = []
        current_start = day_start

        for interval in events:
            free_intervals.append({
                "start": current_start,
                "stop": interval["start"].astimezone(user_timezone).replace(tzinfo=None)
            })
            current_start = interval["stop"].astimezone(user_timezone).replace(tzinfo=None)
        free_intervals.append({
            "start": current_start,
            "stop": day_end
        })
        return http.request.make_json_response(free_intervals)

    @http.route('/connect_elevenlabs/create_event', methods=['POST'], type='http', auth='public',
                csrf=False)
    def create_event(self):
        logger.info('Incoming request: /connect_elevenlabs/create_event')
        if not self.check_tool_token():
            raise Unauthorized()
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        user_id = kwargs.get('user_id')
        if kwargs.get('timezone'):
            tz_val = kwargs['timezone']
            try:
                user_timezone = ZoneInfo(tz_val)
            except (KeyError, ValueError):
                user_timezone = timezone(timedelta(hours=int(tz_val)))
        else:
            user = http.request.env['res.users'].sudo().browse(user_id)
            tz = user.partner_id.tz
            if not tz:
                tz = 'UTC'
            user_timezone = ZoneInfo(tz)

        start_date = datetime.strptime(kwargs.get('start'), "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=user_timezone) \
            .astimezone(ZoneInfo("UTC")) \
            .replace(tzinfo=None)
        stop_date = datetime.strptime(kwargs.get('stop'), "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=user_timezone) \
            .astimezone(ZoneInfo("UTC")) \
            .replace(tzinfo=None)
        event = http.request.env['calendar.event'].sudo().search(
            [('user_id', '=', user_id), ('start', '=', start_date), ('stop', '=', stop_date)])
        if event:
            return http.request.make_json_response({'status': 200, 'detail': 'Event already exist!'})
        http.request.env['calendar.event'].sudo().with_user(user_id).create({
            'name': kwargs.get('name', 'Unknowns'),
            'start': start_date,
            'stop': stop_date,
            'user_id': user_id
        })
        return http.request.make_json_response({'status': 201, 'detail': 'Event successfully created'})

    @http.route('/connect_elevenlabs/get_current_date', methods=['POST'], type='http', auth='public', csrf=False)
    def get_current_date(self):
        logger.info('Incoming request: /connect_elevenlabs/get_current_date')
        if not self.check_tool_token():
            raise Unauthorized()
        return http.request.make_json_response({'current_date': str(datetime.now())})

    @http.route('/connect_elevenlabs/get_meetings', methods=['POST'], type='http', auth='public',
                csrf=False)
    def get_meetings(self):
        logger.info('Incoming request: /connect_elevenlabs/get_meetings')
        if not self.check_tool_token():
            raise Unauthorized()
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return http.request.make_json_response({'status': 400, 'detail': 'partner_id is required'})
        events = http.request.env['calendar.event'].sudo().search(
            [('attendee_ids.partner_id', '=', partner_id)],
            order='start desc'
        ).read(['id', 'name', 'start', 'stop', 'user_id', 'location', 'description'])
        return http.request.make_json_response({'status': 200, 'meetings': events})

    @http.route('/connect_elevenlabs/remove_meeting', methods=['POST'], type='http', auth='public',
                csrf=False)
    def remove_meeting(self):
        logger.info('Incoming request: /connect_elevenlabs/remove_meeting')
        if not self.check_tool_token():
            raise Unauthorized()
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        event_id = kwargs.get('event_id')
        if not event_id:
            return http.request.make_json_response({'status': 400, 'detail': 'event_id is required'})
        try:
            event = http.request.env['calendar.event'].sudo().browse(event_id)
            if not event.exists():
                return http.request.make_json_response({'status': 404, 'detail': 'Event not found'})
            event.unlink()
            return http.request.make_json_response({'status': 200, 'detail': 'Event successfully removed'})
        except Exception as e:
            logger.error(f'Error removing event {event_id}: {str(e)}')
            return http.request.make_json_response(
                {'status': 500, 'detail': f'Error removing event: {str(e)}'})
