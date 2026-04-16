# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ .
ARG VITE_LOGOKIT_TOKEN
ENV VITE_LOGOKIT_TOKEN=$VITE_LOGOKIT_TOKEN
RUN npm run build
# Vite outputs to resolve(__dirname, '../static/dist') → /build/static/dist

# Stage 2: Build Python dependencies
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Runtime
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --create-home appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY . .

# Copy built frontend assets from Stage 1
COPY --from=frontend-builder /build/static/dist static/dist

RUN chmod +x docker-entrypoint.sh

# No hot-reload by default (production). Set UVICORN_ARGS="--reload" for dev.
ENV UVICORN_ARGS=""

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
