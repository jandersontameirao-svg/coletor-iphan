FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 COLLECTOR_DATA=/data \
    COLLECTOR_DEMO_MODE=1 COLLECTOR_EMBEDDED_WORKER=1 COLLECTOR_ALLOW_EMBED=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates poppler-utils tesseract-ocr tesseract-ocr-por && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock /app/
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
RUN useradd --uid 10001 --create-home collector && mkdir /data && chown collector:collector /data
COPY --chown=collector:collector . /app
USER collector
EXPOSE 8000
CMD ["sh","-c","exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
