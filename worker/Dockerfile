FROM python:3.11-slim

RUN apt-get update && apt-get install -y git curl wget tar && rm -rf /var/lib/apt/lists/*
RUN curl -sL https://github.com/google/go-containerregistry/releases/download/v0.19.1/go-containerregistry_Linux_x86_64.tar.gz > crane.tar.gz \
    && tar -zxvf crane.tar.gz crane \
    && mv crane /usr/local/bin/ \
    && rm crane.tar.gz

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# CRIT-04 Fix: Create non-root user matching Kubernetes runAsUser: 1000
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser
USER appuser

CMD ["python", "main.py"]
