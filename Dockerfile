FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git git-lfs ca-certificates \
    && git lfs install --skip-repo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/serve_manifest.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["./entrypoint.sh"]
