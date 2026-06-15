FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install -e .

CMD ["lmserv", "serve", "--catalog", "deploy/models.docker.json", "--port", "8009", "--host", "0.0.0.0"]
