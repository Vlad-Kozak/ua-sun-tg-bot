FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Kyiv

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bot ./bot
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY deploy/healthcheck.py /usr/local/bin/healthcheck.py
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.py

# Бот не потребує root; data/ монтується ззовні і має належати цьому ж uid.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

VOLUME ["/app/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "bot"]
