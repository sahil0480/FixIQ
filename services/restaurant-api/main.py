"""Restaurant API — Restaurant Management System.

Main entry point for the restaurant system.
Coordinates between order-service and payment-gateway.

Customer flow:
  POST /restaurant/order
    → calls order-service
    → calls payment-gateway
    → returns confirmation
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

app = FastAPI(title="Restaurant API")

# Service URLs from environment
ORDER_SERVICE_URL = os.getenv(
    "ORDER_SERVICE_URL",
    "http://order-service"
)
PAYMENT_GATEWAY_URL = os.getenv(
    "PAYMENT_GATEWAY_URL",
    "http://payment-gateway"
)

# Menu
MENU = {
    "burger": 12.99,
    "pizza": 14.99,
    "pasta": 11.99,
    "salad": 8.99,
    "fries": 4.99,
    "cola": 2.99,
    "water": 1.99,
}


class CustomerOrder(BaseModel):
    customer_name: str
    table_number: int
    items: list[str]
    card_last_four: str = "4242"
    special_instructions: str = ""


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "restaurant-api",
        "timestamp": datetime.now().isoformat(),
        "order_service": ORDER_SERVICE_URL,
        "payment_gateway": PAYMENT_GATEWAY_URL,
    }


@app.get("/menu")
def get_menu():
    """Get restaurant menu."""
    return {
        "restaurant": "FixIQ Restaurant",
        "menu": MENU,
        "currency": "EUR",
    }


@app.post("/restaurant/order")
async def place_order(order: CustomerOrder):
    """Place a complete order.

    Flow:
    1. Validate items against menu
    2. Create order in order-service
    3. Process payment in payment-gateway
    4. Return confirmation
    """
    logger.info(
        "New order from %s — table %d: %s",
        order.customer_name,
        order.table_number,
        order.items,
    )

    # Validate items
    invalid_items = [
        item for item in order.items
        if item.lower() not in MENU
    ]
    if invalid_items:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid items: {invalid_items}"
        )

    # Calculate total
    total = sum(
        MENU[item.lower()]
        for item in order.items
    )

    # Step 1 — Create order
    logger.info(
        "Calling order-service for %s",
        order.customer_name,
    )
    try:
        async with httpx.AsyncClient(
            timeout=10.0
        ) as client:
            order_response = await client.post(
                f"{ORDER_SERVICE_URL}/orders",
                json={
                    "customer_name": order.customer_name,
                    "table_number": order.table_number,
                    "items": order.items,
                    "special_instructions": (
                        order.special_instructions
                    ),
                },
            )
            order_data = order_response.json()
            order_id = order_data.get("order_id")
            logger.info(
                "Order %s created successfully",
                order_id,
            )
    except Exception as exc:
        logger.error(
            "order-service failed: %s", exc
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"Order service unavailable: {exc}"
            )
        )

    # Step 2 — Process payment
    logger.info(
        "Calling payment-gateway for €%.2f", total
    )
    try:
        async with httpx.AsyncClient(
            timeout=10.0
        ) as client:
            payment_response = await client.post(
                f"{PAYMENT_GATEWAY_URL}/payments/charge",
                json={
                    "order_id": order_id,
                    "amount": total,
                    "currency": "EUR",
                    "card_last_four": (
                        order.card_last_four
                    ),
                },
            )
            payment_data = payment_response.json()
            payment_id = payment_data.get("payment_id")
            logger.info(
                "Payment %s successful: €%.2f",
                payment_id,
                total,
            )
    except Exception as exc:
        logger.error(
            "payment-gateway failed: %s", exc
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"Payment service unavailable: {exc}"
            )
        )

    return {
        "confirmation_id": str(uuid.uuid4())[:8],
        "order_id": order_id,
        "payment_id": payment_id,
        "customer_name": order.customer_name,
        "table_number": order.table_number,
        "items": order.items,
        "total": f"€{total:.2f}",
        "status": "confirmed",
        "estimated_minutes": order_data.get(
            "estimated_minutes", 20
        ),
        "message": (
            f"Order confirmed! "
            f"Ready in ~{order_data.get('estimated_minutes', 20)} minutes"
        ),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/restaurant/status")
async def restaurant_status():
    """Check status of all services."""
    status = {}

    for service, url in [
        ("order-service", ORDER_SERVICE_URL),
        ("payment-gateway", PAYMENT_GATEWAY_URL),
    ]:
        try:
            async with httpx.AsyncClient(
                timeout=3.0
            ) as client:
                response = await client.get(
                    f"{url}/health"
                )
                status[service] = (
                    "healthy"
                    if response.status_code == 200
                    else "degraded"
                )
        except Exception:
            status[service] = "unreachable"

    all_healthy = all(
        v == "healthy" for v in status.values()
    )

    return {
        "restaurant": "FixIQ Restaurant",
        "overall": (
            "operational" if all_healthy
            else "degraded"
        ),
        "services": status,
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)