# -*- coding: utf-8 -*
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from odoo import http

logger = logging.getLogger(__name__)


class ConnectElevenlabsControllers(http.Controller):

    @http.route('/connect_elevenlabs/get_available_slots/<int:user_id>', methods=['POST'], type='json', auth='public',
                csrf=False)
    def get_available_slots(self, user_id):
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        if kwargs.get('timezone'):
            user_timezone = timezone(timedelta(hours=int(kwargs.get('timezone'))))
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
            date = current_date.strftime('%Y-%m-%d')
        date.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

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
        return free_intervals

    @http.route('/connect_elevenlabs/create_event/<int:user_id>', methods=['POST'], type='json', auth='public',
                csrf=False)
    def create_event(self, user_id):
        kwargs = json.loads(http.request.httprequest.get_data(as_text=True))
        if kwargs.get('timezone'):
            user_timezone = timezone(timedelta(hours=int(kwargs.get('timezone'))))
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

    @http.route('/connect_elevenlabs/get_current_date', methods=['POST'], type='json', auth='public', csrf=False)
    def get_current_date(self):
        return {'current_date': str(datetime.now())}
