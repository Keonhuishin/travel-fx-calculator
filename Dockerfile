FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY exchange_rate_calculator.py .
COPY docs ./docs

EXPOSE 5000

CMD ["gunicorn", "exchange_rate_calculator:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "60"]


