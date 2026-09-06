FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY docker/entrypoint.sh /usr/local/bin/jozani-entrypoint
RUN chmod +x /usr/local/bin/jozani-entrypoint

COPY . .
RUN mkdir -p \
    output/csv \
    output/json \
    output/logs \
    output/debug \
    browser/booking_browser_profile \
    browser/tripadvisor_browser_profile

ENTRYPOINT ["jozani-entrypoint"]
CMD ["python", "main.py"]
