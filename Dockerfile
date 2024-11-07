FROM python:3.10-slim

# Set work directory
WORKDIR /app

# Copy the project files
COPY . /app

# Install necessary dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose the port that FastAPI will use
EXPOSE 8080

# Start FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
