FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CLINIC_DATA_DIR=/data CLINIC_UPLOAD_DIR=/data/uploads \
    CLINIC_BACKUP_DIR=/data/backups CLINIC_DATABASE_URL=sqlite:////data/clinic.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 --retries 10 -r requirements.txt
COPY . .
RUN useradd -r -u 1000 clinic && mkdir -p /data && chown clinic /data
USER clinic
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "python -m app.cli init && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
