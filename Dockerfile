FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config.py .
COPY wsgi.py .

EXPOSE 5000
# --workers 1: the app starts an in-process APScheduler on import via the factory pattern,
# so multiple worker processes would each run their own scheduler and send
# duplicate reminders. Use threads for concurrency instead.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "wsgi:app"]
