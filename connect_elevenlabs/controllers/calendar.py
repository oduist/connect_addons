# -*- coding: utf-8 -*

import json
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from werkzeug.exceptions import Unauthorized

from odoo import http, release

logger = logging.getLogger(__name__)

UTC = ZoneInfo('UTC')
DT_FMT = '%Y-%m-%d %H:%M:%S'
route_type = "json" if release.version_info[0] < 19.0 else 'jsonrpc'

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

    @http.route('/connect_elevenlabs/get_available_slots', methods=['POST'], type=route_type, auth='public',
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
            local_day = datetime.strptime(kwargs['start'], '%Y-%m-%d').date()
        else:
            local_day = datetime.now(user_timezone).date() + timedelta(days=1)

        # The working window is wall-clock time on the requested day, in the
        # caller's timezone. Deriving it from a UTC-converted datetime shifted
        # the whole answer onto the previous day for any zone east of UTC.
        day_start = datetime.combine(local_day, time(8, 0), tzinfo=user_timezone)
        day_end = datetime.combine(local_day, time(18, 0), tzinfo=user_timezone)

        # calendar.event stores naive UTC, so search over the whole local day
        # expressed in UTC.
        utc_from = datetime.combine(
            local_day, time.min, tzinfo=user_timezone
        ).astimezone(UTC).replace(tzinfo=None)
        utc_to = utc_from + timedelta(days=1)

        events = http.request.env['calendar.event'].sudo().search(
            [('user_id', '=', user_id), ('start', '>=', utc_from), ('start', '<', utc_to)],
            order='start asc').read(['name', 'start', 'stop'])

        def to_local(naive_utc):
            """Attach UTC before converting: a naive datetime would otherwise be
            read as the server's local time, which is only harmless while the
            server happens to run on UTC."""
            return naive_utc.replace(tzinfo=UTC).astimezone(user_timezone)

        free_intervals = []
        cursor = day_start
        for event in events:
            start, stop = to_local(event['start']), to_local(event['stop'])
            if stop <= cursor or start >= day_end:
                continue  # entirely outside the working window
            if start > cursor:
                free_intervals.append((cursor, min(start, day_end)))
            cursor = max(cursor, stop)
            if cursor >= day_end:
                break
        if cursor < day_end:
            free_intervals.append((cursor, day_end))

        slots = [
            {'start': a.strftime(DT_FMT), 'stop': b.strftime(DT_FMT)}
            for a, b in free_intervals if b > a
        ]
        logger.debug('Available slots for user %s on %s: %s', user_id, local_day, slots)
        return slots

    @http.route('/connect_elevenlabs/create_event', methods=['POST'], type=route_type, auth='public',
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
            return {'status': 200, 'detail': 'Event already exist!'}
        http.request.env['calendar.event'].sudo().with_user(user_id).create({
            'name': kwargs.get('name', 'Unknowns'),
            'start': start_date,
            'stop': stop_date,
            'user_id': user_id
        })
        return {'status': 201, 'detail': 'Event successfully created'}

    @http.route('/connect_elevenlabs/get_current_date', methods=['POST'], type=route_type, auth='public', csrf=False)
    def get_current_date(self):
        logger.info('Incoming request: /connect_elevenlabs/get_current_date')
        if not self.check_tool_token():
            raise Unauthorized()
        return {'current_date': str(datetime.now())}

    @http.route('/connect_elevenlabs/get_meetings', methods=['POST'], type=route_type, auth='public',
                csrf=False)
    def get_meetings(self):
        logger.info('Incoming request: /connect_elevenlabs/get_meetings')
        if not self.check_tool_token():
            raise Unauthorized()
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        partner_id = kwargs.get('partner_id')
        if not partner_id:
            return {'status': 400, 'detail': 'partner_id is required'}
        events = http.request.env['calendar.event'].sudo().search(
            [('attendee_ids.partner_id', '=', partner_id)],
            order='start desc'
        ).read(['id', 'name', 'start', 'stop', 'user_id', 'location', 'description'])
        return {'status': 200, 'meetings': events}

    @http.route('/connect_elevenlabs/remove_meeting', methods=['POST'], type=route_type, auth='public',
                csrf=False)
    def remove_meeting(self):
        logger.info('Incoming request: /connect_elevenlabs/remove_meeting')
        if not self.check_tool_token():
            raise Unauthorized()
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        event_id = kwargs.get('event_id')
        if not event_id:
            return {'status': 400, 'detail': 'event_id is required'}
        try:
            event = http.request.env['calendar.event'].sudo().browse(event_id)
            if not event.exists():
                return {'status': 404, 'detail': 'Event not found'}
            event.unlink()
            return {'status': 200, 'detail': 'Event successfully removed'}
        except Exception as e:
            logger.error(f'Error removing event {event_id}: {str(e)}')
            return {'status': 500, 'detail': f'Error removing event: {str(e)}'}
