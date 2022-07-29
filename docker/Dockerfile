ARG PYTHON_VERSION=3
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

# Basic configuration file
COPY docker/config.yml .

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY manager.py .

USER nobody

CMD [ "python", "manager.py" ]
