# Dockerfile — Bazoš Scraper
# DevOps Agent | Slim Python image, non-root user, data persistence

FROM python:3.12-slim

# Metadata
LABEL maintainer="Bazoš Scraper" \
      description="24/7 minibagr scraper s Telegram notifikacemi"

# Systémové závislosti
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Bezpečnost: non-root uživatel
RUN useradd --no-create-home --shell /bin/false scraper

# Pracovní adresář
WORKDIR /app

# Nainstalujeme závislosti (oddělená vrstva — cache při změně kódu)
COPY deploy/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Zkopírujeme zdrojový kód (scraper i dashboard)
COPY --chown=scraper:scraper . /app/

# Datový adresář pro seen_ids.json a market.db — persistent volume
RUN mkdir -p /data && chown scraper:scraper /data

# Přepneme na non-root uživatele
USER scraper

# Env proměnné (výchozí hodnoty — přepsat v docker-compose.yml)
ENV LOG_LEVEL=INFO \
    SCRAPE_INTERVAL_MIN=120 \
    SCRAPE_INTERVAL_MAX=300 \
    SEEN_IDS_PATH=/data/seen_ids.json \
    DB_PATH=/data/market.db \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/scraper:/app

WORKDIR /app

# Healthcheck — ověří, že Python process běží
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import scraper; print('OK')"

CMD ["python", "scraper/main.py"]
