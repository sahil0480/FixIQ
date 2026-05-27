"""Order Service — Restaurant Management System.

Manages all orders.
Calls kitchen-service to prepare orders.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException
import httpx
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Order Service")

# Service URLs from environment
KITCHEN_SERVICE_URL = os.getenv(
    "KITCHEN_SERVICE_URL",
    "http://kitchen-service"
)

# In-memory order store
orders: dict[str, dict] = {}


class OrderRequest(BaseModel):
    customer_name: str
    table_number: int
    items: list[str]
    special_instructions: str = ""


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "order-service",
        "timestamp": datetime.now().isoformat(),
        "total_orders": len(orders),
        "kitchen_url": KITCHEN_SERVICE_URL,
    }


@app.post("/orders")
async def create_order(order: OrderRequest):
    """Create a new order and send to kitchen."""
    order_id = str(uuid.uuid4())[:8]

    logger.info(
        "Creating order %s for %s — table %d",
        order_id,
        order.customer_name,
        order.table_number,
    )

    # Save order
    orders[order_id] = {
        "order_id": order_id,
        "customer_name": order.customer_name,
        "table_number": order.table_number,
        "items": order.items,
        "special_instructions": (
            order.special_instructions
        ),
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }

    # Send to kitchen-service
    try:
        async with httpx.AsyncClient(
            timeout=5.0
        ) as client:
            kitchen_response = await client.post(
                f"{KITCHEN_SERVICE_URL}/kitchen/orders",
                json={
                    "order_id": order_id,
                    "items": order.items,
                    "table_number": order.table_number,
                    "priority": "normal",
                },
            )
            kitchen_data = kitchen_response.json()
            orders[order_id]["status"] = "preparing"
            orders[order_id]["estimated_minutes"] = (
                kitchen_data.get("estimated_minutes", 20)
            )
            logger.info(
                "Order %s sent to kitchen. "
                "Est. %d minutes",
                order_id,
                kitchen_data.get(
                    "estimated_minutes", 20
                ),
            )
    except Exception as exc:
        logger.error(
            "Failed to send order %s to kitchen: %s",
            order_id,
            exc,
        )
        orders[order_id]["status"] = "kitchen_error"
        orders[order_id]["error"] = str(exc)

    return orders[order_id]


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    """Get order by ID."""
    if order_id not in orders:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_id} not found"
        )
    return orders[order_id]


@app.get("/orders")
def list_orders():
    """List all orders."""
    return {
        "total": len(orders),
        "orders": list(orders.values()),
    }


@app.put("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    """Cancel an order."""
    if order_id not in orders:
        raise HTTPException(
            status_code=404,
            detail=f"Order {order_id} not found"
        )
    orders[order_id]["status"] = "cancelled"
    orders[order_id]["cancelled_at"] = (
        datetime.now().isoformat()
    )
    logger.info("Order %s cancelled", order_id)
    return orders[order_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)