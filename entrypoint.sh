#!/bin/sh
set -e

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the application
exec "$@"
