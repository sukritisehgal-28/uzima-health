FROM python:3.12-slim
WORKDIR /srv
COPY services/agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared services/shared
COPY services/agent services/agent
CMD ["python", "-m", "services.agent.app.main"]
