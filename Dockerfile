FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY amazon_ops_dashboard ./amazon_ops_dashboard

EXPOSE 8000
CMD ["uvicorn", "amazon_ops_dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
