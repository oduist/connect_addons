# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is an Odoo addons repository for **Oduist Connect**, a comprehensive telephony integration suite that connects Odoo with Twilio for voice calls, SMS, and AI-powered phone services. The codebase consists of multiple interconnected Odoo modules targeting version 19.0, with support for versions 16.0-18.0.

## Core Architecture

### Module Structure
- **connect**: Core module providing Twilio-Odoo integration with call management, recording, and PBX functionality
- **connect_crm**: CRM integration for automatic lead/opportunity creation from calls
- **connect_helpdesk**: Helpdesk ticket integration with phone calls
- **connect_elevenlabs**: AI-powered conversational agents using ElevenLabs voice synthesis
- **connect_elevenlabs_sale**: Sales-specific ElevenLabs integration features  
- **connect_byoc**: Bring Your Own Carrier functionality for custom telephony providers
- **connect_website**: Website integration for click-to-call and lead generation

### Key Models and Data Flow
- **connect.call**: Central call record with status tracking, duration, partner linking, and recording management
- **connect.channel**: Individual call legs/channels that roll up to calls
- **connect.recording**: Audio recordings with transcript and AI summary capabilities
- **connect.user**: PBX users (SIP/Client endpoints) distinct from Odoo res.users
- **connect.number**: Twilio phone numbers with routing configuration
- **connect.callflow**: Visual call routing builder with TwiML generation
- **connect.settings**: Centralized configuration for API keys, features, and behavior

### Integration Patterns
- **Webhook-driven**: Twilio webhooks at `/twilio/webhook/*` drive real-time call state updates
- **AI Services**: OpenAI for transcription/summarization, ElevenLabs for voice synthesis
- **Multi-directional**: Handles inbound DID calls, outbound click-to-call, internal PBX routing
- **Partner-centric**: Automatic partner matching and CRM record creation from phone interactions

## Development Commands

### Installation and Setup
```bash
# Install Python dependencies (run in Odoo environment)
pip3 install twilio elevenlabs==1.59.0 openai phonenumbers httpx

# Install all Connect modules in Odoo
odoo -i connect,connect_crm,connect_helpdesk,connect_elevenlabs -d <database>

# Development mode with auto-reload  
odoo --dev=all -d <database> --addons-path=/path/to/connect_addons/19.0
```

### ElevenLabs Agent Service
The connect_elevenlabs module includes a separate FastAPI service for real-time voice agents:
```bash
cd connect_elevenlabs/service
uv sync
uv run main.py
```

### Testing and CI
The repository uses GitHub Actions for automated testing:
```bash
# Manual testing approach (CI pipeline runs these automatically)
# Test module installation across Odoo versions 16.0-18.0
odoo --test-enable --stop-after-init -i connect,connect_crm,connect_helpdesk,connect_elevenlabs
```

### Version Management
- This is the 19.0 branch - other versions maintained in separate worktrees
- Check `.git/worktrees/` for 16.0, 17.0, 18.0 parallel development branches
- Version-specific compatibility handled in code via `release.version_info` checks

## Key Development Patterns

### Twilio Integration
- All external webhooks use signature verification via `ConnectController.check_signature()`
- Webhook processing runs as `connect.user_connect_webhook` system user
- TwiML responses generated dynamically from `connect.callflow` visual builder
- Call state management follows Twilio's webhook lifecycle (ringing → in-progress → completed)

### AI and Transcription 
- Call recordings automatically trigger OpenAI transcription when `transcript_calls` enabled
- AI summaries posted to partner chatter using configurable `summary_prompt`  
- ElevenLabs integration provides real-time conversational AI agents with tool calling
- Transcript processing uses one-time tokens for secure webhook callbacks

### Multi-tenant Architecture
- Instance registration system with unique UIDs for SaaS deployment
- Customer-specific configuration via `connect.settings` singleton pattern
- Debug mode creates `connect.debug` records for troubleshooting
- Proxy recording serving for secure media access via Odoo authentication

### Security Considerations
- Sensitive fields (API keys, tokens) restricted to `base.group_erp_manager`
- Webhook endpoints use Twilio signature validation
- Media files proxied through authenticated Odoo controllers when `proxy_recordings` enabled
- Separate system user (`connect.user_connect_webhook`) for webhook processing with limited permissions

## Important Files and Locations

- **Controllers**: `connect/controllers/` - HTTP endpoints for webhooks and media serving
- **Models**: `*/models/` - Core business logic and Odoo model definitions  
- **Security**: `*/security/` - Access control rules and user groups
- **Views**: `*/views/` - UI definitions and menu structure
- **Data**: `*/data/` - Default records, cron jobs, and system configuration
- **Migrations**: `connect/migrations/` - Database upgrade scripts between versions
- **Static Assets**: `*/static/src/` - JavaScript components and CSS for phone widgets

## Rules for Linear Integration

When working on Linear issues, include the task ID in commit messages using:
- `ref #TASK_ID` for work in progress
- `closed #TASK_ID` for completed tasks

## Development Notes

- Debug mode can be enabled in Connect settings to create detailed debug logs
- The codebase handles multiple Odoo versions with compatibility checks
- External dependencies must be installed in the Odoo environment (not just dev environment)  
- Webhook URLs must use HTTPS in production for Twilio signature validation
- Use Odoo's context manager patterns for proper user/company switching in webhook handlers