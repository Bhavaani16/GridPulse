# Build from the repo root so /data is inside the context:
#   docker build -f backend/Dockerfile -t gridpulse-backend .
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY data/ /data/

ENV DATA_DIR=/data \
    MODE=cached \
    HARDWARE_MODE=simulated \
    START_SIMULATOR=1 \
    DATABASE_URL=

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
