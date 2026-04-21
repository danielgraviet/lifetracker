FROM python:3.13-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml .
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir \
    "python-telegram-bot[job-queue]>=21.0" \
    "anthropic>=0.40.0" \
    "httpx>=0.27.0" \
    "sqlalchemy[asyncio]>=2.0.0" \
    "asyncpg>=0.30.0" \
    "alembic>=1.13.0" \
    "python-dotenv>=1.0.0" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "pydantic>=2.0.0" \
    "streamlit>=1.40.0" \
    "pandas>=2.0.0" \
    "plotly>=5.0.0" \
    "psycopg2-binary>=2.9.0"

# Copy source and install the package itself (no deps, already installed above)
COPY . .
RUN pip install --no-cache-dir --no-deps .

ENV PYTHONUNBUFFERED=1

# Default to running the API; override per-service in Railway
CMD if [ "$SERVICE" = "bot" ]; then python -m bot.main; elif [ "$SERVICE" = "dashboard" ]; then streamlit run dashboard/app.py --server.port ${PORT:-8501} --server.address 0.0.0.0; else uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}; fi
