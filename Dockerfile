# Build Docker image
docker build -t guru_bot .

# Run with Docker
docker run -d \
  --name guru_bot \
  -p 8080:8080 \
  --env-file .env \
  guru_bot

# Or use docker-compose
docker-compose up -d

# Check logs
docker logs -f guru_bot