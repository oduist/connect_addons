FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

# Copy application source
COPY main.py twilio_audio_interface.py ./

EXPOSE 48000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "48000"]
