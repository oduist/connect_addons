# Oduist Memory — Hindsight gateway service
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY hindsight_gateway.py ./

ENV PYTHONUNBUFFERED=1

# Runs the poll loop. Pass `--once` via `command` to run a single cycle.
ENTRYPOINT ["python", "hindsight_gateway.py"]
