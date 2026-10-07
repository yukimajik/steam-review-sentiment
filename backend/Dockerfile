FROM python:3.13-slim

WORKDIR /code

# Install dependencies before copying the code, so Docker can reuse this layer
# when only the code changes (much faster rebuilds).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/

EXPOSE 8000
# Hosts like Render say which port to listen on in $PORT (Render uses 10000); locally it's 8000.
# "exec" makes uvicorn the main process, so it receives the shutdown signal directly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
