# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend + Playwright
FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg and Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[explorer,mcp]" || true
COPY . .
RUN pip install --no-cache-dir -e ".[explorer,mcp]"

# Install Playwright browser + system deps
RUN playwright install --with-deps chromium

# Copy built frontend assets
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Entrypoint runs migrations before starting
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
