"""
FastAPI Distributed Abacus Microservice
Handles requests across multiple nodes
Uses Redis for distributed state management
"""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import redis.asyncio as redis
from typing import Optional
import os
import logging
import asyncio
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

#reddis management
class RedisManager:
    """Manages Redis connection pool for distributed state"""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.lock_timeout = 10  # seconds
        self.retry_delay = 0.01  # seconds

    async def connect(self):
        """Initialize Redis connection pool"""
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_db = int(os.getenv("REDIS_DB", 0))

        try:
            self.redis_client = await redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30
            )
            # Test connection
            await self.redis_client.ping()
            logger.info(f"✅ Connected to Redis at {redis_host}:{redis_port}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")

    async def get_sum(self) -> int:
        """Get current sum with strong consistency"""
        try:
            value = await self.redis_client.get("abacus:sum")
            return int(value) if value else 0
        except Exception as e:
            logger.error(f"Error getting sum: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve sum")

    async def add_to_sum(self, number: int) -> int:
        """
        Add number to sum with distributed lock for strong consistency
        Uses optimistic locking with retry mechanism
        """
        max_retries = 100
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Use WATCH for optimistic locking
                async with self.redis_client.pipeline(transaction=True) as pipe:
                    while True:
                        try:
                            # Watch the key for changes
                            await pipe.watch("abacus:sum")

                            # Get current value
                            current = await pipe.get("abacus:sum")
                            current_sum = int(current) if current else 0

                            # Calculate new sum
                            new_sum = current_sum + number

                            # Start transaction
                            pipe.multi()
                            pipe.set("abacus:sum", new_sum)

                            # Execute transaction
                            await pipe.execute()

                            logger.info(f"✅ Added {number} to sum. New total: {new_sum}")
                            return new_sum

                        except redis.WatchError:
                            # Another client modified the key, retry
                            retry_count += 1
                            logger.warning(f"⚠️ Conflict detected, retry {retry_count}/{max_retries}")
                            await asyncio.sleep(self.retry_delay)
                            continue

            except Exception as e:
                logger.error(f"Error adding to sum: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to add number: {str(e)}")

        raise HTTPException(status_code=503, detail="Max retries exceeded - high contention")

    async def reset_sum(self) -> bool:
        """Reset sum to 0"""
        try:
            await self.redis_client.set("abacus:sum", 0)
            logger.info("✅ Sum reset to 0")
            return True
        except Exception as e:
            logger.error(f"Error resetting sum: {e}")
            raise HTTPException(status_code=500, detail="Failed to reset sum")

    async def get_stats(self) -> dict:
        """Get operational statistics"""
        try:
            info = await self.redis_client.info()
            return {
                "connected_clients": info.get("connected_clients", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "used_memory_human": info.get("used_memory_human", "N/A"),
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}


#fastapi lifecycle
redis_manager = RedisManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown"""
    # Startup
    logger.info("🚀 Starting FastAPI Abacus Microservice")
    await redis_manager.connect()

    # Initialize sum to 0 if not exists
    if await redis_manager.redis_client.get("abacus:sum") is None:
        await redis_manager.redis_client.set("abacus:sum", 0)
        logger.info("Initialized sum to 0")

    yield

    # Shutdown
    logger.info("🛑 Shutting down FastAPI Abacus Microservice")
    await redis_manager.disconnect()


#define app
app = FastAPI(
    title="Distributed Abacus Microservice",
    description="A high-throughput, distributed abacus service with strong consistency",
    version="1.0.0",
    lifespan=lifespan
)


class NumberInput(BaseModel):
    """Input model for adding a number"""
    number: int = Field(..., description="Number to add to the running sum")

    class Config:
        json_schema_extra = {
            "example": {
                "number": 42
            }
        }


class SumResponse(BaseModel):
    """Response model for sum queries"""
    sum: int = Field(..., description="Current running sum")
    timestamp: str = Field(..., description="Timestamp of the response")
    node_id: str = Field(..., description="ID of the node that processed the request")


class AddResponse(BaseModel):
    """Response model for add operations"""
    new_sum: int = Field(..., description="New sum after addition")
    added: int = Field(..., description="Number that was added")
    timestamp: str = Field(..., description="Timestamp of the operation")
    node_id: str = Field(..., description="ID of the node that processed the request")


class ResetResponse(BaseModel):
    """Response model for reset operations"""
    message: str = Field(..., description="Status message")
    timestamp: str = Field(..., description="Timestamp of the operation")
    node_id: str = Field(..., description="ID of the node that processed the request")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    node_id: str
    redis_connected: bool
    current_sum: int
    stats: dict


def get_node_id() -> str:
    """Get unique node identifier"""
    return os.getenv("NODE_ID", f"node-{os.getpid()}")


def get_timestamp() -> str:
    """Get current timestamp"""
    return datetime.utcnow().isoformat()

#set up endpoints

#default get
@app.get("/", tags=["General"])
async def root():
    """Root endpoint - API information"""
    return {
        "service": "Distributed Abacus Microservice",
        "version": "1.0.0",
        "node_id": get_node_id(),
        "endpoints": {
            "POST": "/abacus/number - Add a number to the sum",
            "GET": "/abacus/sum - Get current sum",
            "DELETE": "/abacus/sum - Reset sum to 0",
            "GET": "/health - Health check"
        }
    }

#add using post
@app.post(
    "/abacus/number",
    response_model=AddResponse,
    tags=["Abacus"],
    summary="Add number to running sum",
    description="Adds a number to the current running sum with strong consistency across all nodes"
)
async def add_number(data: NumberInput):
    """
    Add a number to the running sum.

    This endpoint:
    - Supports high throughput (10-100-1000 req/min)
    - Maintains strong consistency across multiple nodes
    - Uses Redis optimistic locking for conflict resolution
    - Automatically retries on conflicts
    """
    new_sum = await redis_manager.add_to_sum(data.number)

    return AddResponse(
        new_sum=new_sum,
        added=data.number,
        timestamp=get_timestamp(),
        node_id=get_node_id()
    )

#get sum
@app.get(
    "/abacus/sum",
    response_model=SumResponse,
    tags=["Abacus"],
    summary="Get current sum",
    description="Retrieves the current running sum with strong consistency"
)
async def get_sum():
    """
    Get the current running sum.

    This endpoint:
    - Provides strongly consistent reads
    - Low latency (Redis in-memory reads)
    - Safe to call frequently
    """
    current_sum = await redis_manager.get_sum()

    return SumResponse(
        sum=current_sum,
        timestamp=get_timestamp(),
        node_id=get_node_id()
    )

#reset the sum
@app.delete(
    "/abacus/sum",
    response_model=ResetResponse,
    tags=["Abacus"],
    summary="Reset sum to 0",
    description="Resets the running sum to 0"
)
async def reset_sum():
    """
    Reset the running sum to 0.

    This operation is atomic and consistent across all nodes.
    """
    await redis_manager.reset_sum()

    return ResetResponse(
        message="Sum successfully reset to 0",
        timestamp=get_timestamp(),
        node_id=get_node_id()
    )

#health check
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["General"],
    summary="Health check",
    description="Check service health and get operational statistics"
)
async def health_check():
    """
    Health check endpoint.

    Returns:
    - Service status
    - Node ID
    - Redis connection status
    - Current sum
    - Operational statistics
    """
    try:
        current_sum = await redis_manager.get_sum()
        stats = await redis_manager.get_stats()
        redis_connected = True
    except Exception as e:
        current_sum = -1
        stats = {}
        redis_connected = False

    return HealthResponse(
        status="healthy" if redis_connected else "unhealthy",
        node_id=get_node_id(),
        redis_connected=redis_connected,
        current_sum=current_sum,
        stats=stats
    )


#middleware for logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    start_time = datetime.utcnow()

    response = await call_next(request)

    process_time = (datetime.utcnow() - start_time).total_seconds()
    logger.info(
        f"{request.method} {request.url.path} "
        f"completed in {process_time:.4f}s "
        f"[Node: {get_node_id()}]"
    )

    return response


#entry point
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=False,  
        log_level="info"
    )
