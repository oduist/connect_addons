# Connect — Admin Guide

Everything an administrator configures in Connect: the Twilio account, who may
do what, phone numbers and routing, recordings and their storage, transcription,
and messaging.

All of it lives under **Connect ▸ Settings** and **Connect ▸ Voice**, and all of
it requires the Connect **Admin** group.

## Access model

Connect defines two privileges under the **Connect** category:

| Privilege | Group | Meaning |
| --- | --- | --- |
| Connect | **Admin** | Full configuration: settings, numbers, routing, users, messaging setup. |
| Connect | **User** | Day-to-day use: the phone, the call log, messages. |
| Connect | **Webhook** | Service account only — used by the provider's callbacks, never assign it to a person. |
| Recording | **Do not record** | Calls of this user are not recorded. Deliberately a separate privilege, so it combines with any access level. |

Two consequences worth knowing:

- The whole **Connect** app menu is restricted to Admin and User. A user in
  neither group does not see Connect at all, no matter what other rights they
  hold — including a system administrator.
- The **Webhook** group belongs to the service user the module creates on
  install. Its password is what the provider authenticates with, so treat it as
  a credential, not as a login for staff.

## General settings

**Connect ▸ Settings ▸ General**, tab **General**:

| Setting | What it controls |
| --- | --- |
| **Odoo URL** | The address the provider calls back on. It must be reachable from the internet, otherwise inbound calls and status updates never arrive. Change it via the button next to the field, which opens the underlying system parameter. |
| **Fallback URL** | A second address used when the primary one fails. |
| **Debug mode** | Verbose logging of provider traffic into the Debug menu. Leave it off in production; the log grows fast. |
| **Current Balance** | Reads the account balance from Twilio on demand, via the button. |

## API keys

Tab **API Keys**.

**Twilio** — find these in the [Twilio Console](https://console.twilio.com/):

| Field | Notes |
| --- | --- |
| **Account SID** | The account identifier. |
| **Auth Token** | The account's main secret. Stored write-only: the form shows a masked value. |
| **Region** | Twilio region. For anything other than `us1` a **Region Auth Token** is required, and the field becomes mandatory. |
| **API Key SID** / **API Key Secret** | Used for the web phone's access tokens. The secret is readable only by users with ERP-manager rights. |
| **Edge** | The Twilio edge location traffic goes through. Pick the one closest to your users; the default is `ashburn`. |

After entering credentials press **SYNC TWILIO ACCOUNT** — it pulls the account
configuration into Odoo. Do this once at setup, and again whenever you change
numbers directly in the Twilio Console.

**OpenAI** — one field, the API key, readable only by ERP managers. It is needed
for call summaries whatever the transcription provider, for transcription when
OpenAI is the selected provider, and for generated chatter messages. Leave it
empty if you use none of these.

**Self-hosted Whisper** — a speech-to-text server you run yourself that speaks
the OpenAI transcription API (for example vLLM serving Whisper). Fill these in
only if you select it as the provider on the **Transcription** tab.

| Field | Notes |
| --- | --- |
| **API URL** | The server's base URL including `/v1`, e.g. `http://192.168.1.10:9000/v1`. Odoo must be able to reach it. |
| **API Key** | The server's bearer key. Stored write-only, like the OpenAI key; leave it empty if the server needs none. |
| **TEST CONNECTION** | Asks the server for its model list and shows the result, or the error. Use it after any change. |

The connection is plain HTTP unless your server provides HTTPS, so it carries
the key and the call audio unencrypted: keep the server on a private network or
a VPN such as Tailscale, never on the open internet.

## Calls

Tab **Calls**.

| Setting | What it controls |
| --- | --- |
| **System Voice** | The voice used for all system prompts — call-flow messages, voicemail, transfers. |
| **Proxy recordings** | On (the default), recordings are streamed through Odoo using the listener's Odoo login. Turn it off only if you also remove the HTTP auth on the Twilio side, otherwise playback breaks. |
| **Fetch call prices** | Pulls the price of each call from Twilio after it completes. Useful for cost reporting, but it adds a delay to call processing — it runs as a scheduled job, see Automation below. |
| **FORMAT NUMBERS** | A one-off action that rewrites stored numbers into international format. Run it after importing contacts. |

**Call duration limit.** Outbound and inbound legs are capped by the
`call_duration_limit` Connect parameter, expressed in seconds. It is applied to
the dial itself, so a runaway call cannot bill indefinitely.

**Pronunciation rules.** A JSON map of text-to-pronunciation substitutions, for
words the text-to-speech engine gets wrong — for example
`{"3CHI": "3-chee", "CEO": "C-E-O"}`.

## Recordings and S3 storage

By default recordings stay with Twilio and Odoo plays them from there. Tab
**S3 Storage** moves them into a bucket you own.

Enable **Store recordings in S3** to reveal the configuration, then work down
the page in order — the form is written as a checklist because the steps depend
on each other:

1. **Bucket prefix.** Every bucket name is forced to start with it, and the
   generated IAM policy is scoped to it. The default is `oduist-connect-`; set
   your own to match an existing naming convention.
2. **IAM policy.** The form generates a least-privilege policy for the prefix
   you chose. Create an AWS IAM user, attach this policy to it, and create an
   access key for it. The form spells out the console clicks.
3. **Access key.** Paste the Access Key ID and Secret, pick the region, and give
   the bucket a name — the full name is prefix + name and is shown read-only
   below the field.
4. **Folder and retention.** The folder (prefix inside the bucket) defaults to
   `recordings`. Retention of `0` keeps audio forever; any positive number
   installs an S3 lifecycle rule that deletes the **audio file** after that many
   days. The recording record and its transcript stay in Odoo — so the history
   survives, only the audio goes.
5. **CREATE / CONFIGURE S3 BUCKET** provisions the bucket with those settings.
6. **CREATE TWILIO AWS CREDENTIAL** registers the AWS key with Twilio, and the
   resulting credential SID is shown on the form. Use **RECREATE** if you rotate
   the AWS key — it deletes the old credential and issues a new one, and the new
   SID must then be re-selected in the Twilio Console.
7. **Finish in the Twilio Console.** Twilio has no API for voice external
   storage, so this last step is manual: Voice → Recordings → Settings, enable
   external S3 storage, pick the `connect-s3-recordings` credential, paste the
   S3 URL shown on the Odoo form, and save.

Only recordings created **after** this is finished land in your bucket; existing
ones keep playing from Twilio.

## Transcription

Tab **Transcription**, in three groups.

**Speech-to-text**

| Setting | What it controls |
| --- | --- |
| **Transcript provider** | Which engine turns speech into text: **Open AI** (the default), **Self-hosted Whisper**, or **Elevenlabs** when that module is installed. |
| **Model** | Self-hosted Whisper only. The model name the server expects; default `whisper-1`. |
| **Language** | Self-hosted Whisper only. A language code (`en`, `fr`, `ru`...) when you know what language your calls are in. Leave it empty and the server detects it from the start of each recording. |
| **Transcript calls** | Transcribe and summarise call recordings automatically, shortly after each recording arrives. Needs the OpenAI key, because the summary always comes from OpenAI. |
| **Transcribe voice messages** | Transcribe incoming WhatsApp and MMS voice messages; the text becomes the message body. |

What each provider covers:

| Provider | Call recordings | Voicemail and voice messages | Call summary |
| --- | --- | --- | --- |
| Open AI | Open AI | Open AI | Open AI |
| Self-hosted Whisper | Whisper | Whisper | Open AI |
| Elevenlabs | Elevenlabs | Open AI | Open AI |

Voicemail is transcribed shortly after it arrives whenever its provider is
configured — the OpenAI key, or the Whisper URL when Whisper is selected; there
is no separate switch for it. A recording, a voicemail or a message whose
transcription failed shows the reason in its *Transcription error* field.

**Transcription runs in the background.** A new recording or voicemail, or a
press of **Transcribe**, only puts it in a queue; the scheduled action
**Connect: transcribe queued audio** (Settings → Technical → Scheduled
Actions) works through that queue right away, one item at a time, voicemail
before recordings. Until then the record shows *Transcription queued*. A user
who pressed **Transcribe** gets a notification when the transcript is ready
or failed. This needs Odoo's cron workers — `max_cron_threads` of at least 1
in the Odoo configuration (the Odoo default is 2). With no cron workers, or
with that scheduled action archived, nothing is transcribed and records stay
queued. Its 10-minute interval is only a safety net; there is no need to
shorten it. Voice messages are the exception: they are still transcribed
while the message is received, because the text becomes the message body.

**Call Summary** — shown when *Transcript calls* is on.

| Setting | What it controls |
| --- | --- |
| **Summary prompt** | The instruction sent to OpenAI when summarising a call. The default is "Summarise this phone call"; make it specific to your business and the summaries get markedly more useful. A user's own *Record Summary Prompt* replaces it for that user's calls. |
| **Register summary** | Posts the summary to the chatter of the related partner, so it shows up in the contact's history. |

**Transcribe Rules** — shown when *Transcript calls* is on. Decides which
recorded calls are transcribed automatically. Each rule has a **Calling
Number** and a **Called Number** pattern. A call is transcribed when at least
one rule matches both its caller and the number it called. Patterns are
regular expressions matched anywhere in the number, so `.+` matches any
number and `3658257665` matches that number with or without the `+1`.

**An empty list transcribes nothing.** *Transcript calls* on its own is not
enough: add at least one rule. To transcribe every call, add one rule with
`.+` in both columns. Use narrower patterns to skip internal or high-volume
automated traffic. Rules apply only to automatic transcription; the
**Transcribe** button on a recording ignores them.

Transcription costs money per call at OpenAI and Elevenlabs, and the rules are
the lever that keeps that bill predictable. A self-hosted Whisper server costs
nothing per call, but each summary is still an OpenAI request.

Limits worth knowing:

- **Size.** One recording may be at most 25 MB. Recordings kept at Twilio are
  fetched as MP3, which fits calls of 50 minutes and more; recordings stored in
  S3 are sent as stored.
- **Protected media.** If your Twilio account enforces HTTP authentication on
  media URLs (the Voice and Messaging settings in the Twilio Console), Connect
  still downloads recordings, voicemail and voice messages: it signs in with
  the Account SID and Auth Token from the API Keys tab. A wrong or revoked
  token shows on the recording as `401 Client Error: Unauthorized`.
- **Self-hosted Whisper** gives no speaker labels: the transcript is timestamped
  lines, not a dialogue. How well it detects the language depends on the
  server — some are set up to choose among a few languages only — so set
  **Language** when your calls are all in one. After the server restarts, its
  first transcription waits while the model loads, which can take minutes. Odoo
  waits up to five minutes per transcription; the `WHISPER_HTTP_TIMEOUT`
  environment variable of the Odoo server (in seconds) changes that.

## Chatter

Tab **Chatter** holds the prompt used when Connect generates a chatter message
from a conversation. It is one text field, and the same advice applies: the more
specific the prompt, the more useful the result.

## Development

Tab **Development** is visible only in developer mode and holds
**Twilio verify requests** — whether incoming webhook requests are validated
against Twilio's signature. Keep it on in production. Turning it off makes the
webhook endpoints accept unsigned requests, which is only ever appropriate while
debugging against a tunnel.

## Voice configuration

Under **Connect ▸ Voice**:

| Menu | Purpose |
| --- | --- |
| **Domains** | SIP domains used for registration and routing. |
| **Users** | The link between an Odoo user and their phone: extension, SIP phone, web phone, priorities and ring timeouts, voicemail, outgoing caller ID, fallback destination. |
| **Extensions** | Internal numbers and what they point at. |
| **PBX Groups** | Groups of Connect users that ring together. |
| **Numbers** | Your provider numbers and what happens to calls arriving on them. |
| **Call Flows** | The routing logic calls follow. |
| **TwiML** | Raw TwiML applications, for behavior the call flows do not cover. |
| **Outgoing CallerIds** | The numbers users may present when calling out. |
| **Recordings** | The recording archive. |
| **Calls** | The call log. |

Per-user phone setup worth calling out, since it decides whether a person can be
reached at all:

- **SIP phone** and **Web phone** are enabled independently, each with its own
  **priority** (which rings first) and **ring timeout** (how long before the
  call moves on).
- **Fallback destination** decides what happens when nobody answers — voicemail,
  another extension, or a mobile number.
- **Record calls** is a per-user switch, and the **Do not record** group
  overrides it for people whose calls must never be recorded.
- **Extension** is created from the user form with the **Extension** button.

## Messaging configuration

Under **Connect ▸ Messaging** (all admin-only except the message list itself):

| Menu | Purpose |
| --- | --- |
| **Configuration** | How inbound and outbound messages are handled. |
| **WhatsApp Senders** | The WhatsApp numbers you send from. A Connect user can be tied to a specific sender. |
| **WhatsApp Templates** | Pre-approved templates. Required for messaging a customer outside the 24-hour window WhatsApp allows for free-form replies — without templates, agents simply cannot start a conversation. |
| **Messages** | The SMS and WhatsApp log, including failures with the provider's error. |

## Automation

Connect ships two scheduled jobs:

| Job | Schedule | What it does |
| --- | --- | --- |
| **Vacuum Connect debug** | daily | Clears out old provider debug records, so the debug log cannot grow without bound. |
| **Fetch Call Prices from Twilio** | every 5 minutes | Pulls call prices, when **Fetch call prices** is enabled. |

Note that scheduled jobs are disabled in most disposable development
environments, so on a test instance the price data will simply not appear.

## Licensing

**Connect ▸ Settings ▸ License** holds the instance registration: the instance
identifier, the registration number, the license token, and which Oduist modules
are covered. It is also where you opt in to security alerts, onboarding and
update notifications.

On a development or demo database the license check logs a warning about a
missing instance hash. That is expected there and does not affect telephony.

## Health checks after setup

Work through these once, in order, and a broken link shows up immediately rather
than during a customer call:

1. The **Odoo URL** is reachable from the public internet.
2. **SYNC TWILIO ACCOUNT** completes without an error and the balance loads.
3. A test user has a web phone enabled and an extension, and their browser has
   microphone permission.
4. An outbound call to a mobile connects, and shows up in **Voice ▸ Calls**.
5. An inbound call to one of your numbers rings the right person or group.
6. A recording plays back in Odoo — and, if you configured S3, lands in your
   bucket rather than at Twilio.
7. An SMS sends and its status turns to delivered in **Messaging ▸ Messages**.
