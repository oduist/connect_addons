# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCallEventProjector(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings = cls.env["connect.settings"].sudo()
        cls.settings.set_param("delete_processed_call_events", False)
        cls.event_model = cls.env["connect.call.event"].sudo()
        cls.call_model = cls.env["connect.call"].sudo()
        cls.root_sid = "CA_PROJECTOR_ROOT"
        cls.base_payload = {
            "CallSid": cls.root_sid,
            "Direction": "inbound",
            "Caller": "+15550000001",
            "Called": "+15550000002",
            "To": "+15550000002",
            "CallStatus": "ringing",
            "SequenceNumber": "0",
        }
        cls.call = cls.call_model.ensure_initial_call(cls.base_payload)

    def test_ingest_is_idempotent(self):
        first = self.event_model.ingest(
            "call_status", self.base_payload, token="same-token"
        )
        second = self.event_model.ingest(
            "call_status", self.base_payload, token="same-token"
        )
        self.assertEqual(first, second)
        self.assertEqual(
            self.event_model.search_count(
                [("dedup_key", "=", first.dedup_key)]
            ),
            1,
        )

    def test_older_sequence_cannot_regress_channel(self):
        completed = dict(
            self.base_payload,
            CallStatus="completed",
            SequenceNumber="2",
            CallDuration="12",
        )
        self.event_model.ingest("call_status", completed, token="sequence-2")
        self.event_model.process_pending_events()
        channel = self.env["connect.channel"].search(
            [("sid", "=", self.root_sid)]
        )
        self.assertEqual(channel.status, "completed")
        self.assertEqual(channel.sequence_number, 2)

        stale = dict(
            self.base_payload,
            CallStatus="in-progress",
            SequenceNumber="1",
            CallDuration="3",
        )
        self.event_model.ingest("call_status", stale, token="sequence-1")
        self.event_model.process_pending_events()
        self.assertEqual(channel.status, "completed")
        self.assertEqual(channel.duration, 12)
        self.assertEqual(channel.sequence_number, 2)

    def test_timestamp_orders_events_without_sequence(self):
        channel = self.call.channels[:1]
        channel.write(
            {
                "status": "ringing",
                "duration": 0,
                "sequence_number": 4,
                "event_timestamp": "2026-01-01 00:00:00",
            }
        )
        payload = dict(
            self.base_payload,
            CallStatus="completed",
            CallDuration="6",
            Timestamp="2026-01-01T00:00:05Z",
        )
        payload.pop("SequenceNumber")
        self.event_model.ingest(
            "call_status", payload, token="timestamp-only"
        )
        self.event_model.process_pending_events()
        self.assertEqual(channel.status, "completed")
        self.assertEqual(channel.duration, 6)
        self.assertEqual(channel.sequence_number, 4)

    def test_voicemail_is_projected(self):
        payload = {
            "CallSid": self.root_sid,
            "RecordingUrl": "https://example.invalid/recording",
            "RecordingDuration": "9",
        }
        self.event_model.ingest(
            "voicemail_status", payload, token="voicemail"
        )
        self.event_model.process_pending_events()
        self.assertEqual(
            self.call.voicemail_url, "https://example.invalid/recording"
        )
        self.assertEqual(self.call.voicemail_duration, 9)

    def test_unknown_parent_is_retried(self):
        payload = {
            "CallSid": "CA_UNKNOWN_CHILD",
            "ParentCallSid": "CA_UNKNOWN_PARENT",
            "Direction": "outbound-dial",
            "Caller": "+15550000001",
            "Called": "sip:100@example.invalid",
            "To": "sip:100@example.invalid",
            "CallStatus": "ringing",
            "SequenceNumber": "0",
        }
        event = self.event_model.ingest(
            "call_status", payload, token="unknown-parent"
        )
        self.event_model.process_pending_events()
        self.assertEqual(event.state, "pending")
        self.assertTrue(event.next_attempt_at)
        self.assertIn("has not arrived", event.error_message)

    def test_generic_dial_action_does_not_create_transfer_channel(self):
        attempt = self.env["connect.call.attempt"].create(
            {
                "kind": "ring_group",
                "call_id": self.call.id,
                "parent_sid": self.root_sid,
                "expected_count": 2,
            }
        )
        payload = {
            "CallSid": self.root_sid,
            "DialCallSid": "CA_GENERIC_DIAL_CHILD",
            "DialCallStatus": "no-answer",
            "DialCallDuration": "0",
            "ConnectActionModel": "connect.callflow",
            "ConnectActionRecordId": 42,
        }
        event = self.event_model.ingest(
            "dial_action", payload, token="generic-dial"
        )
        self.event_model.process_pending_events()
        self.assertEqual(event.state, "done")
        self.assertEqual(attempt.state, "resolved")
        self.assertFalse(
            self.env["connect.channel"].search(
                [("sid", "=", "CA_GENERIC_DIAL_CHILD")]
            )
        )

    def test_generic_dial_action_cannot_regress_leg_status(self):
        child = self.env["connect.channel"].create(
            {
                "sid": "CA_GENERIC_EXISTING_CHILD",
                "call": self.call.id,
                "parent_channel": self.call.channels[:1].id,
                "parent_sid": self.root_sid,
                "technical_direction": "outbound-dial",
                "status": "completed",
                "duration": 8,
                "sequence_number": 3,
            }
        )
        self.event_model.ingest(
            "dial_action",
            {
                "CallSid": self.root_sid,
                "DialCallSid": child.sid,
                "DialCallStatus": "no-answer",
                "DialCallDuration": "0",
                "ConnectActionModel": "connect.user",
                "ConnectActionRecordId": 42,
            },
            token="generic-dial-stale",
        )
        self.event_model.process_pending_events()
        self.assertEqual(child.status, "completed")
        self.assertEqual(child.duration, 8)

    def test_transfer_command_is_prepared_for_postcommit(self):
        self.env["connect.call.attempt"].create(
            {
                "kind": "external_leg",
                "call_id": self.call.id,
                "parent_sid": self.root_sid,
                "external_sid": "CA_EXTERNAL_LEG",
            }
        )
        transfer = self.env["connect.call.attempt"].create(
            {
                "kind": "transfer",
                "call_id": self.call.id,
                "parent_sid": self.root_sid,
                "dial_call_sid": "CA_TRANSFER_CHILD",
            }
        )
        event = self.event_model.ingest(
            "dial_action",
            {
                "CallSid": self.root_sid,
                "DialCallSid": "CA_TRANSFER_CHILD",
                "DialCallStatus": "completed",
                "DialCallDuration": "7",
                "ConnectActionModel": "connect.call",
            },
            token="transfer-command",
        )
        self.event_model.process_pending_events()
        self.assertEqual(transfer.state, "resolved")
        self.assertEqual(event.command_state, "pending")
        self.assertEqual(
            event.command_payload["call_sid"], "CA_EXTERNAL_LEG"
        )

    def test_immediate_retention_deletes_done_event(self):
        self.settings.set_param("delete_processed_call_events", True)
        payload = dict(
            self.base_payload,
            CallStatus="in-progress",
            SequenceNumber="3",
        )
        event = self.event_model.ingest(
            "call_status", payload, token="delete-done"
        )
        event_id = event.id
        dedup_key = event.dedup_key
        self.event_model.process_pending_events()
        self.assertFalse(self.event_model.browse(event_id).exists())
        duplicate = self.event_model.ingest(
            "call_status", payload, token="delete-done"
        )
        self.assertFalse(duplicate)
        self.assertEqual(
            self.env["connect.call.event.dedup"].search_count(
                [("dedup_key", "=", dedup_key)]
            ),
            1,
        )

    def test_finalization_releases_the_parking_slot(self):
        """A parked caller who hangs up must not keep holding the slot.

        The registration outlives the call otherwise, and every later
        retrieval of that slot resolves to it instead of the caller actually
        waiting there.
        """
        self.call.write(
            {"park_slot": "705", "park_call_sid": self.root_sid}
        )
        payload = dict(
            self.base_payload,
            CallStatus="completed",
            SequenceNumber="7",
            CallDuration="30",
        )
        self.event_model.ingest("call_status", payload, token="park-release")
        self.event_model.process_pending_events()
        self.call.invalidate_recordset()
        self.assertIn(self.call.status, ("completed", "no-answer"))
        self.assertFalse(self.call.park_slot)
        self.assertFalse(self.call.park_call_sid)
        self.assertFalse(
            self.env["connect.call"]._get_parked_call("705")
        )
