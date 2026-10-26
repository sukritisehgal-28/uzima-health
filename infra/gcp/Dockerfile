FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services ./services
COPY data ./data
COPY infra/gcp/runtime.py ./runtime.py
RUN useradd --create-home --uid 10001 uzima
USER uzima
CMD ["python", "runtime.py"]
