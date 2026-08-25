# Simple Dockerfile for the Prospect Research Agent backend.
# Not required to run the app locally on Windows (see README) -- provided
# for later containerized deployment via the root docker-compose.yml.
FROM python:3.11-slim

# WeasyPrint's native dependencies (Pango/Cairo/GDK-Pixbuf/etc). If any of
# these are unavailable on a slimmer base image, the app still runs fine --
# app/stages/stage5_render.py falls back to fpdf2 automatically.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/pdfs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
