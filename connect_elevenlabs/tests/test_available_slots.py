# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odoo.tests import tagged
from odoo.tests.common import HttpCase

ENDPOINT = "/connect_elevenlabs/get_available_slots"
TOKEN = "test-agent-token"
#: UTC+3 in September. The bug this file guards only showed east of UTC.
TZ_NAME = "Europe/Chisinau"
TZ = ZoneInfo(TZ_NAME)
OFFSET = timedelta(hours=3)
DAY = "2026-09-03"
DT_FMT = "%Y-%m-%d %H:%M:%S"


@tagged("post_install", "-at_install", "connect_elevenlabs")
class TestAvailableSlots(HttpCase):
    """The agent's availability lookup.

    It must answer for the day the caller asked about, expressed in the
    caller's timezone, and clamped to the 08:00-18:00 working window.
    """

    def setUp(self):
        super().setUp()
        self.env["connect.settings"].sudo().set_param("elevenlabs_agent_token", TOKEN)
        self.owner = self.env["res.users"].create({
            "name": "Slots Owner",
            "login": "slots-owner",
        })

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _utc(day, hhmm):
        """A local wall-clock time on `day`, as the naive UTC calendar.event stores."""
        return datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M") - OFFSET

    def _meeting(self, local_start, local_stop, day=DAY, user=None, name="Busy"):
        return self.env["calendar.event"].create({
            "name": name,
            "start": self._utc(day, local_start),
            "stop": self._utc(day, local_stop),
            "user_id": (user or self.owner).id,
        })

    def _post(self, token=TOKEN, **payload):
        body = dict({"user_id": self.owner.id, "timezone": TZ_NAME}, **payload)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["x-elevenlabs-agent-token"] = token
        self.env.flush_all()
        return self.url_open(ENDPOINT, data=json.dumps(body), headers=headers)

    def _slots(self, **payload):
        response = self._post(**payload)
        self.assertEqual(response.status_code, 200)
        return response.json()["result"]

    def _pairs(self, slots):
        return [(s["start"], s["stop"]) for s in slots]

    # -- the regression --------------------------------------------------
    def test_answers_for_the_day_that_was_asked_for(self):
        """The whole working day, dated as requested.

        Turning the requested day into local midnight and then into UTC lands
        at 21:00 the evening before for UTC+3, and the window used to be built
        from that shifted date -- so this returned 2026-09-02.
        """
        self.assertEqual(
            self._pairs(self._slots(start=DAY)),
            [(f"{DAY} 08:00:00", f"{DAY} 18:00:00")],
        )

    def test_default_day_is_tomorrow_where_the_caller_is(self):
        """With no day named, tomorrow is the caller's tomorrow, not the server's."""
        expected = (datetime.now(TZ) + timedelta(days=1)).date().isoformat()
        slots = self._slots()
        self.assertTrue(slots, "a free day should yield one slot")
        self.assertTrue(
            all(s["start"].startswith(expected) for s in slots),
            f"expected slots on {expected}, got {slots}",
        )

    # -- the arithmetic --------------------------------------------------
    def test_free_time_is_the_gaps_between_meetings(self):
        self._meeting("09:00", "10:00")
        self._meeting("12:30", "13:30")
        self.assertEqual(
            self._pairs(self._slots(start=DAY)),
            [
                (f"{DAY} 08:00:00", f"{DAY} 09:00:00"),
                (f"{DAY} 10:00:00", f"{DAY} 12:30:00"),
                (f"{DAY} 13:30:00", f"{DAY} 18:00:00"),
            ],
        )

    def test_meeting_running_past_the_window_ends_the_day(self):
        """No interval may come back reversed.

        A meeting finishing at 20:00 used to leave a final slot of
        start 20:00 / stop 18:00, which an agent would read out as free time.
        """
        self._meeting("17:00", "20:00")
        slots = self._slots(start=DAY)
        self.assertEqual(
            self._pairs(slots), [(f"{DAY} 08:00:00", f"{DAY} 17:00:00")]
        )
        for slot in slots:
            self.assertLess(slot["start"], slot["stop"], f"reversed interval: {slot}")

    def test_meeting_before_the_window_leaves_the_day_free(self):
        self._meeting("06:00", "07:00")
        self.assertEqual(
            self._pairs(self._slots(start=DAY)),
            [(f"{DAY} 08:00:00", f"{DAY} 18:00:00")],
        )

    def test_meeting_on_another_day_is_not_counted(self):
        self._meeting("09:00", "10:00", day="2026-09-04", name="Next day")
        self.assertEqual(
            self._pairs(self._slots(start=DAY)),
            [(f"{DAY} 08:00:00", f"{DAY} 18:00:00")],
        )

    def test_another_users_meeting_is_not_counted(self):
        stranger = self.env["res.users"].create({
            "name": "Someone Else", "login": "someone-else",
        })
        self._meeting("09:00", "10:00", user=stranger, name="Not ours")
        self.assertEqual(
            self._pairs(self._slots(start=DAY)),
            [(f"{DAY} 08:00:00", f"{DAY} 18:00:00")],
        )

    # -- the contract the agent reads ------------------------------------
    def test_every_boundary_is_a_plain_datetime_string(self):
        """The agent parses these; both ends must be the same shape."""
        self._meeting("09:00", "10:00")
        for slot in self._slots(start=DAY):
            for edge in ("start", "stop"):
                self.assertIsInstance(slot[edge], str)
                datetime.strptime(slot[edge], DT_FMT)  # raises if the shape drifts

    # -- the gate --------------------------------------------------------
    def _assert_refused(self, response):
        """The route is jsonrpc, so the refusal is an error envelope, not a 401.

        The controller raises werkzeug's Unauthorized, but Odoo's jsonrpc
        dispatcher turns any exception into a 200 carrying `error`. A caller
        cannot tell it was refused from the status code alone -- it has to read
        the body.
        """
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("result", payload)
        self.assertEqual(
            payload["error"]["data"]["name"], "werkzeug.exceptions.Unauthorized"
        )

    def test_a_request_without_the_token_is_refused(self):
        self._assert_refused(self._post(token=None, start=DAY))

    def test_a_request_with_the_wrong_token_is_refused(self):
        self._assert_refused(self._post(token="nope", start=DAY))

    def test_a_refused_request_leaks_no_availability(self):
        self._meeting("09:00", "10:00")
        payload = self._post(token="nope", start=DAY).json()
        self.assertNotIn("result", payload)
