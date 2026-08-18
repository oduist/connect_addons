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
