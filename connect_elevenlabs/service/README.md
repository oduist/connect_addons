# ElevenLabs Connect Service

AI-powered call handling service with ElevenLabs TTS/STT integration for Twilio.

## Local Development

```shell
uv sync
uv run main.py
```

## Environment Setup

Create `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

Configure the following variables:
- `ELEVENLABS_API_KEY` - Your ElevenLabs API key
- `ODOO_USER` - Odoo connection user
- `ODOO_PASSWORD` - Odoo connection password
- `ODOO_DB` - Odoo database name
- `ODOO_URL` - Odoo instance URL

## Docker

### Build Image

```bash
docker build -t connect-elevenlabs-agent:latest .
```

### Run with Docker

```bash
docker run --env-file .env -p 48000:48000 connect-elevenlabs-agent:latest
```

The service will be available at `http://localhost:48000`

## Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  connect-elevenlabs-agent:
    build: .
    ports:
      - "48000:48000"
    env_file:
      - .env
    restart: unless-stopped
```

### Run

```bash
docker-compose up -d
```

### Stop

```bash
docker-compose down
```

### View Logs

```bash
docker-compose logs -f connect-elevenlabs-agent
```
