FROM python:3.10-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Set the default port to 8080, which can be overridden
ENV PORT 8080

# Expose the port for Docker purposes (internal documentation)
EXPOSE 8080

# Run Uvicorn with dynamic port handling
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
