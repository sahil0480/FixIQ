"""Kitchen Service — Restaurant Management System.

Receives orders from order-service.
Manages kitchen display and order preparation.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Kitchen Service")

# In-memory order queue
orders: dict[str, dict] = {}


class Order(BaseModel):
    order_id: str
    items: list[str]
    table_number: int
    priority: str = "normal"


class OrderStatus(BaseModel):
    order_id: str
    status: str
    estimated_minutes: int


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "kitchen-service",
        "timestamp": datetime.now().isoformat(),
        "orders_in_queue": len(orders),
    }


@app.post("/kitchen/orders")
def receive_order(order: Order):
    """Receive a new order from order-service."""
    logger.info(
        "Kitchen received order %s: %s",
        order.order_id,
        order.items,
    )

    # Simulate kitchen processing
    estimated = random.randint(10, 30)

    orders[order.order_id] = {
        "order_id": order.order_id,
        "items": order.items,
        "table_number": order.table_number,
        "status": "preparing",
        "received_at": datetime.now().isoformat(),
        "estimated_minutes": estimated,
    }

    logger.info(
        "Order %s queued. Est. %d minutes",
        order.order_id,
        estimated,
    )

    return {
        "order_id": order.order_id,
        "status": "preparing",
        "estimated_minutes": estimated,
        "message": "Order received by kitchen",
    }


@app.get("/kitchen/orders/{order_id}")
def get_order_status(order_id: str):
    """Get status of an order."""
    if order_id not in orders:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_id} not found"
        )
    return orders[order_id]


@app.get("/kitchen/orders")
def list_orders():
    """List all orders in kitchen queue."""
    return {
        "total": len(orders),
        "orders": list(orders.values()),
    }


@app.put("/kitchen/orders/{order_id}/ready")
def mark_ready(order_id: str):
    """Mark an order as ready."""
    if order_id not in orders:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_id} not found"
        )
    orders[order_id]["status"] = "ready"
    orders[order_id]["ready_at"] = (
        datetime.now().isoformat()
    )
    logger.info("Order %s is ready!", order_id)
    return orders[order_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)