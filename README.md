# Distributed Abacus Microservice - FastAPI

A high-throughput, distributed microservice built with FastAPI and Redis for maintaining a consistent running sum across multiple nodes.

## Features

1. Uses Redis with optimistic locking
2. Handles 1000+ requests/minute  
3. Runs correctly across multiple nodes  
4. Retries on concurrent modifications  
5. Health checks, logging, graceful shutdown enabled
6. Easy deployment with Docker Compose 

## Requirements

- Python 3.12+
- Redis 7+
- Docker & Docker Compose (for multi-node deployment)

## Installation

### Option 1: Local Development (Single Node)

1. **Install Redis** (if not already installed):
```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# Or use Docker
docker run -d -p 6379:6379 redis:7-alpine
```

2. **Install Python dependencies**:
```bash
pip install -r requirements.txt
```

3. **Run the application**:
```bash
python app.py
```

The API will be available at `http://localhost:8000`

### Option 2: Docker Compose (Multi-Node)

This is the **recommended** way to test distributed behavior.

1. **Build and start all services**:
```bash
# Start 2 nodes + Redis
docker-compose up --build

# Or start in background
docker-compose up -d

# To start 3 nodes (node3 is optional)
docker-compose --profile full up --build
```

2. **Services will be available at**:
   - Node 1: `http://localhost:8001`
   - Node 2: `http://localhost:8002`
   - Node 3: `http://localhost:8003` (if using --profile full)
   - Redis: `localhost:6379`

3. **Stop services**:
```bash
docker-compose down

# Remove volumes too
docker-compose down -v
```

## API Endpoints

### 1. Add Number to Sum
```http
POST /abacus/number
Content-Type: application/json

{
  "number": 42
}
```

**Response**:
```json
{
  "new_sum": 42,
  "added": 42,
  "timestamp": "2025-11-07T18:30:00.123456",
  "node_id": "node-1"
}
```

### 2. Get Current Sum
```http
GET /abacus/sum
```

**Response**:
```json
{
  "sum": 42,
  "timestamp": "2025-11-07T18:30:01.234567",
  "node_id": "node-2"
}
```

### 3. Reset Sum
```http
DELETE /abacus/sum
```

**Response**:
```json
{
  "message": "Sum successfully reset to 0",
  "timestamp": "2025-11-07T18:30:02.345678",
  "node_id": "node-1"
}
```

### 4. Health Check
```http
GET /health
```

**Response**:
```json
{
  "status": "healthy",
  "node_id": "node-1",
  "redis_connected": true,
  "current_sum": 42,
  "stats": {
    "connected_clients": 3,
    "total_commands_processed": 1234,
    "used_memory_human": "1.23M"
  }
}
```

## Project Structure

```
fastapi_abacus/
├── app.py                 # Main FastAPI application
├── requirements.txt       # Python dependencies
├── Dockerfile            # Container image definition
├── docker-compose.yml    # Multi-node orchestration   
└── README.md             # This file
```

## How It Works

### Request Flow

```
Client → Load Balancer → [Node 1, Node 2, Node 3] → Redis
                              ↓         ↓        ↓
                              └─────────┴────────┘
                                   Same Sum
```

### Concurrency Handling

**Scenario**: Two nodes simultaneously add 10 and 20

```
Time  | Node 1          | Node 2          | Redis Sum
------|-----------------|-----------------|----------
t0    | WATCH sum       | WATCH sum       | 0
t1    | GET sum = 0     | GET sum = 0     | 0
t2    | MULTI           | MULTI           | 0
t3    | SET sum = 10    | SET sum = 20    | 0
t4    | EXEC ✓          | EXEC ✗ (retry)  | 10
t5    |                 | WATCH sum       | 10
t6    |                 | GET sum = 10    | 10
t7    |                 | MULTI           | 10
t8    |                 | SET sum = 30    | 10
t9    |                 | EXEC ✓          | 30
```

Final result: **30** (correct!)

