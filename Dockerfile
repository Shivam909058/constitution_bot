FROM python:3.10-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose port 8080 (this is for documentation purposes)
EXPOSE 8080

# Set a default value for PORT, which can be overridden by the deployment environment
ENV PORT 8080

# Use an entrypoint to dynamically pass the port
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port $PORT"]
