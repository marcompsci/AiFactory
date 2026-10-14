FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git util-linux && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 aiciv
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest
COPY services ./services
COPY packages/shared-types/seed ./packages/shared-types/seed
COPY packages/world-engine/src/districts.json ./packages/world-engine/src/districts.json
COPY packages/event-contracts/schema ./packages/event-contracts/schema
COPY docs/architecture ./docs/architecture
USER aiciv
ENV AICIV_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
