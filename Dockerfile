FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COLLECTOR_DATA=/var/lib/coletor \
    COLLECTOR_DEMO_MODE=1 \
    COLLECTOR_ALLOW_EMBED=1

WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY . .
RUN mkdir -p /var/lib/coletor

EXPOSE 3000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-3000}"]
