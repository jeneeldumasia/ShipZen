FROM python:3.11.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create non-root user matching Kubernetes runAsUser: 1000
RUN addgroup --system appgroup && adduser --system --ingroup appgroup --uid 1000 appuser
USER appuser

EXPOSE 8000

# 4 workers by default; override via WEB_CONCURRENCY env var per environment
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4}"]
