FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY config.py .
COPY wsgi.py .
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENV FLASK_APP=wsgi:app

EXPOSE 5000
# --workers 1: the app starts an in-process APScheduler on import via the factory pattern,
# so multiple worker processes would each run their own scheduler and send
# duplicate reminders. Use threads for concurrency instead.
# Invoke via `sh` so it works even when the ./:/app bind mount shadows the image
# copy and the host file has lost its executable bit (e.g. after unzip on deploy).
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "wsgi:app"]
