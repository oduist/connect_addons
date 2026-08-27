# Connect ElevenLabs — User Guide

This module gives Connect a voice AI agent: a conversational assistant that
answers calls, talks to the caller, and can hand the conversation over to a
person or to another agent when it reaches the limit of what it should handle.

For you as a user this mostly shows up in two places — calls answered by an
agent look slightly different in the call log, and voice prompts around your
phone can be spoken in a real voice rather than a synthetic one.

## Calls handled by an agent

Open a call in **Connect ▸ Voice ▸ Calls**. When the call was handled by an AI
agent, the record carries:

- **Agent** — which agent took the call;
- **Summary** — what the conversation was about, in a few lines;
- the **transcript** — the full text of what was said, by both sides;
- a **player** for the conversation audio, so you can listen without leaving
  Odoo.

That is the fast way to answer "what did the customer actually want" for a call
nobody in your team was present for.

Recordings carry the same treatment: **Connect ▸ Voice ▸ Recordings** shows the
transcript and the summary alongside the audio.

## Talking to an agent, and being transferred by one

A caller reaches an agent because a phone number or an extension points at it.
From the caller's side it is an ordinary phone call — they talk, the agent
answers.

An agent can be configured to transfer the conversation. Two kinds exist, and
which one happens depends on how your administrator set it up:

- **to another agent** — for example a general-purpose agent handing over to one
  specialised in billing;
- **to a person** — the call arrives at an extension the way any other call
  does, and your phone rings normally.

When a call reaches you this way, the caller has already been talking to the
agent. The call's transcript and summary tell you what was said before you
picked up — worth a glance before you say hello.

## Booking appointments

An agent can work with the Odoo calendar during the call: it reads free time
out of a colleague's calendar, offers it to the caller, and books the meeting
before hanging up. The module ships an **Appointment Assistant** agent template
for exactly this, so a booking agent is something your administrator can set up
without writing a prompt from scratch.

Four things a caller can ask for:

| The caller says | The agent does |
| --- | --- |
| "When are you free on Thursday?" | Reads the gaps between existing meetings that day and offers them. |
| "Book me in at two, then" | Creates the meeting in the calendar. |
| "What have I got booked?" | Lists the meetings that caller is an attendee of. |
| "Cancel the one on Friday" | Deletes that meeting. |

What you see afterwards is an ordinary calendar event, in the calendar of the
person it was booked for, with the call that produced it carrying the transcript
and summary of what was agreed.

### What the agent treats as free

Free time is worked out by taking a **single day**, for a **single person**, and
finding the gaps between the meetings already in their calendar. Two limits
follow from that, and both matter on the phone:

- **The working day is fixed at 08:00–18:00.** It is not read from working
  schedules, and it does not know about public holidays or time off. A caller
  can be offered 09:00 on a day that person is not working.
- **Only calendar events count as busy.** Anything that keeps a colleague
  occupied without being in their calendar is invisible to the agent.

If the caller does not name a day, the agent looks at **tomorrow**.

Times are spoken in the caller's timezone where the agent knows it, and stored
in the calendar the usual way, so what you see on your side is your own local
time.

### Two habits worth having

- **Check a booking against the transcript** if anything about it looks odd.
  Dates and times taken by ear go wrong the same way quantities do, and "Thursday
  the 14th" is not always both.
- **A cancellation is a deletion.** When the agent cancels a meeting the event is
  removed, not archived — there is no cancelled copy left behind to notice later.
  If a meeting you expected has simply gone, the linked call's transcript is the
  record of who asked for it.

Booking against a double-booked slot is prevented: an identical meeting for the
same person at the same start and end time is not created twice.

## Voices in the phone system

Prompts your callers hear — call-flow messages, your voicemail greeting — can be
played in an ElevenLabs voice instead of the standard synthetic one. Available
voices are managed centrally by your administrator; you do not pick them per
call.

If your administrator enabled it for you, your **voicemail prompt** can use one
of these voices, and you can listen to the result in your user settings before
callers ever hear it.

## What you cannot do yourself

Creating agents, writing their prompts, giving them tools, connecting them to
numbers and extensions, and choosing voices are all administrator work — an
agent's prompt decides what it says to your customers, so it is deliberately not
a per-user setting. See the Admin Guide.
