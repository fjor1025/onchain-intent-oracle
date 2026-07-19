#!/bin/bash
set -e

echo "Setting up OnChainIntentOracle database..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker first."
    exit 1
fi

# Start services
docker compose up -d postgres redis

# Wait for Postgres to be ready
echo "Waiting for Postgres..."
until docker compose exec -T postgres pg_isready -U oio > /dev/null 2>&1; do
    sleep 1
done

echo "Postgres is ready!"

# Run init script
docker compose exec -T postgres psql -U oio -d oio < scripts/init-db.sql

echo "Database setup complete!"
echo "Connection: postgresql://oio:oio@localhost:5432/oio"
