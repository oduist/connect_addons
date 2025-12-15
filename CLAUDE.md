# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is the **Oduist Connect** repository - a collection of Odoo addon modules that integrate Twilio telephony (voice calls, SMS, WhatsApp) and ElevenLabs AI conversational agents with Odoo. The repository contains 7 modules organized in a modular architecture for different features and integrations.

## Repository Structure

### Core Modules

- **connect** - Main Twilio-Odoo integration (voice calls, WhatsApp, SMS)
- **connect_byoc** - Bring Your Own Carrier functionality (€499)
- **connect_crm** - CRM integration for lead tracking from calls
- **connect_elevenlabs** - AI conversational agents using ElevenLabs
- **connect_elevenlabs_sale** - Sales management extension for AI agents (€999)
- **connect_helpdesk** - Helpdesk ticket integration
- **connect_website** - Website snippets for click-to-call

### Branch Strategy

- **Current working branch**: `19.0` (Odoo 19.0)
- **Main branch for PRs**: `18.0` (Odoo 18.0)
- Version branches correspond to Odoo major versions

## Development Commands

### Odoo Module Development

This is an Odoo addon repository. Modules are installed and tested within an Odoo instance.

**Install a module:**
```bash
# From Odoo instance, install via Apps menu or:
odoo-bin -i connect -d your_database
```

**Upgrade a module after changes:**
```bash
odoo-bin -u connect -d your_database
```

**Restart Odoo with auto-reload:**
```bash
odoo-bin --dev=all -d your_database
```

### ElevenLabs Service (Standalone Python Service)

The `connect_elevenlabs/service/` directory contains a standalone FastAPI service that bridges Twilio calls with ElevenLabs AI.

**Setup:**
```bash
cd connect_elevenlabs/service
cp .env.example .env
# Edit .env with your credentials
uv sync
```

**Run the service:**
```bash
cd connect_elevenlabs/service
uv run main.py
```

**Required environment variables:**
- `ELEVENLABS_API_KEY` - ElevenLabs API key
- `ODOO_URL` - Full Odoo instance URL (e.g., https://your-instance.odoo.com)
- `ODOO_DB` - Database name
- `ODOO_USER` - Odoo user (typically 'connect')
- `ODOO_PASSWORD` - Odoo user password

## Architecture Overview

### Webhook-Driven Architecture

All real-time telephony events flow through Twilio webhooks:

```
Twilio → Odoo Webhook Controller → Model Business Logic → Database → UI Update
```

**Key webhook controller:** `connect/controllers/twilio_webhooks.py`
- 11 webhook routes handling domain routing, call status, messages, recordings
- Request signature verification for security
- Uses special webhook user (`connect.user_connect_webhook`)

### Core Models (connect/models/)

**Call Management:**
- `connect.call` - Master call record (user-facing)
- `connect.channel` - Individual call legs (A-leg, B-leg technical tracking)
- `connect.recording` - Call recordings with OpenAI transcription

**Communication:**
- `connect.message` - WhatsApp and SMS messages (bidirectional)
- `connect.whatsapp_sender` - WhatsApp Business number management

**PBX Infrastructure:**
- `connect.user` - PBX users with SIP/WebRTC credentials
- `connect.exten` - Extensions (like traditional PBX: 101, 102, etc.)
- `connect.domain` - Twilio SIP domains
- `connect.number` - Phone numbers
- `connect.callflow` - IVR/call routing flows
- `connect.twiml` - TwiML applications

**Configuration:**
- `connect.settings` - Single-record model storing all configuration (API keys, regions, features)

### Two-Tier Call Tracking

- **connect.call** - High-level call record that users see
- **connect.channel** - Low-level tracking of individual call legs (for transfers, conferences)

### Extension System (PBX-like)

Extensions (`connect.exten`) can point to:
- Users (ring their phone)
- Call flows (IVR menus)
- TwiML applications (custom logic)

Uses Reference field pattern for polymorphic destinations.

### WhatsApp Integration

**Incoming messages flow:**
```
WhatsApp User → Twilio → /twilio/webhook/message → connect.message.receive()
```

**Message Configuration** (`connect.message_configuration`):
- Routes incoming messages to specific Odoo models (Partner, Lead, Ticket)
- Pattern matching on sender/recipient numbers
- Automatic record creation

### ElevenLabs Service Architecture

```
┌─────────────┐         ┌──────────────────┐         ┌──────────────┐
│   Twilio    │ WebRTC  │   FastAPI        │  HTTP   │    Odoo      │
│   Phone     │◄───────►│   Service        │◄───────►│   Instance   │
│   Call      │         │  (main.py)       │         │              │
└─────────────┘         └──────────────────┘         └──────────────┘
                               │
                               │ WebSocket
                               ▼
                        ┌──────────────┐
                        │  ElevenLabs  │
                        │  Conv. AI    │
                        └──────────────┘
```

**Components:**
- `main.py` - FastAPI WebSocket handler, ElevenLabs integration, Odoo RPC connection
- `twilio_audio_interface.py` - Audio format conversion between Twilio and ElevenLabs

**AI Agents** (`connect.elevenlabs_agent` model):
- Configurable voice, prompt, temperature, LLM model
- Supports GPT-4, Claude, Gemini, Grok
- 30+ language support
- Custom tools/functions for Odoo queries and transfers

### Frontend Architecture

**Technology:** Odoo OWL framework (Odoo Web Library)

**Main phone component:** `connect/static/src/components/phone/phone/phone.js`
- Floating phone widget with drag-and-drop positioning
- Twilio JS SDK for WebRTC
- BroadcastChannel API for cross-tab call synchronization
- Tabs: Contacts, Favorites, Call History
- Features: Mute, hold, transfer, DTMF keypad

**Services:**
- `active_calls` - System-wide call state management
- `actions` - Phone actions (dial, hangup)
- `mail` - Integration with Odoo mail/chatter

## Code Patterns and Conventions

### Settings Model Pattern

Single-record model for configuration (`connect/models/settings.py`):
- Uses `get_param()` and `set_param()` methods
- Protected fields for auth tokens (limited to security groups)
- Stores Twilio credentials, regions, API keys

### Webhook Security

All webhooks validate Twilio signatures:
```python
validator = RequestValidator(auth_token)
signature = request.headers.get('X-Twilio-Signature')
is_valid = validator.validate(url, data, signature)
```

### Reference Field Pattern

Used for polymorphic relationships (e.g., messages/calls can link to any model):
```python
record = fields.Reference(
    selection='_selection_target_model',
    string='Related Record'
)
```

### Phone Number Normalization

Always use E.164 format via `phonenumbers` library:
```python
import phonenumbers
parsed = phonenumbers.parse(number, region)
formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
```

### TwiML Generation

Three methods used throughout:
1. Static TwiML XML (stored in `connect.twiml`)
2. TwiPy (Python code that generates TwiML)
3. Model methods (e.g., `connect.domain.route_call()`)

### Migration System

- Migrations in `connect/migrations/` folder
- Version-based folders (0.6, 0.7, 0.8, 0.9, 1.0.1, 1.0.5, 1.0.6)
- Includes pre-migrate and post-migrate scripts

## Security

### Security Groups

- `connect.group_connect_admin` - Full administrative access
- `connect.group_connect_user` - Regular user access
- Special webhook user with minimal permissions for API calls

### Record Rules

- User-level record rules in `security/user_record_rules.xml`
- Admin-level record rules in `security/admin_record_rules.xml`

## External Dependencies

### Python Packages (Odoo modules)

**connect:**
- `twilio` - Twilio Python SDK
- `openai` - For call transcription
- `phonenumbers` - Phone number parsing/formatting
- `httpx` - Async HTTP client

**connect_elevenlabs:**
- `elevenlabs==1.59.0` - ElevenLabs Python SDK

### Python Packages (ElevenLabs service)

See `connect_elevenlabs/service/pyproject.toml`:
- `fastapi[standard]>=0.115.11`
- `uvicorn>=0.34.0`
- `websockets>=15.0.1`
- `elevenlabs==1.59.0`
- `twilio>=9.5.1`
- `aio-odoorpc` - Async Odoo RPC
- `python-dotenv>=1.0.1`

### JavaScript

- Twilio Client JS SDK (WebRTC)
- Odoo OWL framework

## Important Files

### Configuration
- `connect/models/settings.py` - All Twilio/Connect settings
- `connect_elevenlabs/service/.env` - Service environment variables (not committed)
- `connect_elevenlabs/service/.env.example` - Template for service config

### Webhooks
- `connect/controllers/twilio_webhooks.py` - All Twilio webhook handlers

### Main Models
- `connect/models/call.py` - Call management (~627 lines)
- `connect/models/message.py` - WhatsApp/SMS messages (~517 lines)
- `connect/models/user.py` - PBX users (~461 lines)
- `connect_elevenlabs/models/agent.py` - AI agent configuration

### Frontend
- `connect/static/src/components/phone/phone/phone.js` - Main phone widget
- `connect/static/src/services/active_calls/` - Call state management

### Service
- `connect_elevenlabs/service/main.py` - FastAPI WebSocket service
- `connect_elevenlabs/service/twilio_audio_interface.py` - Audio streaming

## Manifest Files

Each module has a `__manifest__.py` defining:
- Module metadata (name, version, author, price)
- Dependencies
- External Python dependencies
- Data files (security, views, data)
- Assets (JavaScript, CSS)

## Documentation References

- [Connect Knowledge Base](https://oduist.com/knowledge/article/32)
- [Installation Video](https://www.youtube.com/watch?v=wPvkV3A-7Sw)

## Key Architectural Insights

1. **Stateless Webhooks** - All webhooks are stateless; state stored in database models
2. **Async Service** - ElevenLabs service uses async Python for real-time AI conversations
3. **Modular Design** - Each integration module extends core independently
4. **Multi-channel** - Same infrastructure handles voice calls, WhatsApp, and SMS
5. **Edge Computing** - Twilio edge support for low-latency global deployment (8 regions)
6. **Real-time UI** - WebRTC in browser, BroadcastChannel for multi-tab synchronization
7. **Security First** - Signature verification, special webhook users, group-based access control
