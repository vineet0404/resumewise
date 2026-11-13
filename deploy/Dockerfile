# ResumeWise web app. Build from the project root:  docker build -f deploy/Dockerfile -t resumewise .
FROM python:3.13-slim

# tesseract = optional OCR for scanned PDFs; postgresql-client = pg_dump for `manage.py backup`
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-mar tesseract-ocr-tel postgresql-client \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt
COPY core ./core
COPY backend ./backend
RUN useradd --create-home --uid 10001 app && mkdir -p /backups && chown app /backups
USER app
WORKDIR /app/backend
EXPOSE 8000
# 4 workers x 4 threads; OCR can take a while, hence the long timeout.
CMD ["gunicorn", "config.wsgi:application", "-b", "0.0.0.0:8000", "-w", "4", "--threads", "4", "--timeout", "120", "--access-logfile", "-"]
