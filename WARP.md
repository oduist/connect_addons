# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This repository contains Oduist Connect Odoo modules - a collection of Odoo addons that integrate Twilio telephony services with Odoo ERP, along with advanced AI-powered conversational agents via ElevenLabs.

## Core Commands

### Python Dependencies Management
```bash
# Install Python dependencies for the modules
pip install -r requirements.txt

# For Odoo 17.0 on official docker image with specific version constraints:
pip3 install twilio elevenlabs typing_extensions==4.10.0 openai==1.39.0 --break-system-packages

# For Ubuntu 20.04 environments with version constraints:
pip install httpx==0.27.2 openai==1.55.3
```

### ElevenLabs Service Management
```bash
# Navigate to the ElevenLabs service directory
cd connect_elevenlabs/service/

# Install service dependencies using uv
uv sync

# Run the ElevenLabs service
uv run main.py
```

### Odoo Development Commands
```bash
# Install specific Connect modules in Odoo
odoo -i connect,connect_crm,connect_elevenlabs

# Update modules after code changes
odoo -u connect,connect_crm,connect_elevenlabs

# Run Odoo with debugging enabled
odoo --dev=all
```

## Module Architecture

This codebase follows Odoo's standard module structure with several interconnected addons:

### Core Module Hierarchy

**`connect`** - Base module providing core Twilio integration:
- **Models**: Call management (`connect.call`), settings (`connect.settings`), users, channels, recordings
- **Controllers**: Webhook handling (`twilio_webhooks.py`), media serving (`main.py`)
- **Key Features**: Call tracking, recording management, SIP/Client integration, partner matching

**Extension Modules** (all depend on `connect`):
- **`connect_crm`** - CRM integration for lead management and call tracking
- **`connect_elevenlabs`** - AI conversational agents with voice synthesis
- **`connect_byoc`** - Bring Your Own Carrier functionality
- **`connect_helpdesk`** - Helpdesk ticket integration
- **`connect_website`** - Website click-to-call functionality

### Key Architectural Patterns

**Call Flow Management**: The system uses a channel-based architecture where:
- `connect.channel` represents individual call legs
- `connect.call` aggregates channels into complete call records
- Call direction is determined by technical flow analysis (inbound/outbound-api/internal)

**AI Agent System** (`connect_elevenlabs`):
- Agents are configured with voice, LLM models, and tools
- Real-time conversation handling via WebSocket connections
- Knowledge base integration for context-aware responses
- Tool system for dynamic function calling (calendar, CRM operations)

**Settings Management**: Centralized configuration via `connect.settings` model:
- Single record pattern for global settings
- Protected field handling for sensitive data (API keys, tokens)
- Instance registration and version checking

**Security Architecture**:
- Role-based access control with custom groups (`connect.group_*`)
- Webhook authentication via Twilio request verification
- Record-level rules for multi-company environments

### Integration Points

**Twilio Integration**:
- Webhook endpoints for call status updates
- TwiML generation for call flow control
- Media proxy for recordings and voicemails
- SIP/Client registration management

**OpenAI Integration**:
- Call transcription via OpenAI Whisper
- Call summarization using configurable prompts
- Partner message logging integration

**ElevenLabs Integration**:
- Conversational AI agents with voice synthesis
- Real-time audio streaming via WebSocket
- Multi-language support with voice cloning
- Dynamic tool execution during conversations

## Development Patterns
## Same python codebase for all branches
We try to keep the same python code for different Odoo versions and when there are different API we create conditional blocks, e.g.:
```python
if release.version_info[0] >= 17.0:
    recording_widget = fields.Html(compute='_get_recording_data', sanitize=False)
else:
    recording_widget = fields.Char(compute='_get_recording_data')
```

### Debug System
Leverage the built-in debug system:
```python
from odoo.addons.connect.models.settings import debug

debug(self, "Debug message", level="info")
```
Do not use debug when handling errors.

## External Dependencies Note

This codebase has specific version constraints for OpenAI and HTTPX libraries due to compatibility issues. Always refer to `requirements.txt` comments when encountering TypeErrors related to proxies or unexpected keyword arguments.

## Documentation Resources

- [Connect Knowledge Base](https://oduist.com/knowledge/article/32)
