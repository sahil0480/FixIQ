"""Payment Gateway — Restaurant Management System.

Processes payments for orders.
Handles charges, refunds and payment status.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Payment Gateway")

# In-memory payment store
payments: dict[str, dict] = {}


class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    currency: str = "EUR"
    card_last_four: str = "4242"


class RefundRequest(BaseModel):
    payment_id: str
    reason: str


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "payment-gateway",
        "timestamp": datetime.now().isoformat(),
        "total_payments": len(payments),
    }


@app.post("/payments/charge")
def charge(payment: PaymentRequest):
    """Process a payment charge."""
    logger.info(
        "Processing payment for order %s: €%.2f",
        payment.order_id,
        payment.amount,
    )

    # Simulate payment processing
    payment_id = str(uuid.uuid4())[:8]

    # 95% success rate simulation
    if random.random() < 0.95:
        status = "success"
        logger.info(
            "Payment %s successful: €%.2f",
            payment_id,
            payment.amount,
        )
    else:
        status = "failed"
        logger.error(
            "Payment %s failed for order %s",
            payment_id,
            payment.order_id,
        )

    payments[payment_id] = {
        "payment_id": payment_id,
        "order_id": payment.order_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": status,
        "card_last_four": payment.card_last_four,
        "timestamp": datetime.now().isoformat(),
    }

    if status == "failed":
        raise HTTPException(
            status_code=402,
            detail="Payment failed — please retry"
        )

    return {
        "payment_id": payment_id,
        "order_id": payment.order_id,
        "amount": payment.amount,
        "status": status,
        "message": "Payment processed successfully",
    }


@app.get("/payments/{payment_id}")
def get_payment(payment_id: str):
    """Get payment status."""
    if payment_id not in payments:
        raise HTTPException(
            status_code=404,
            detail=f"Payment {payment_id} not found"
        )
    return payments[payment_id]


@app.post("/payments/refund")
def refund(request: RefundRequest):
    """Process a refund."""
    if request.payment_id not in payments:
        raise HTTPException(
            status_code=404,
            detail=f"Payment {request.payment_id} not found"
        )

    payment = payments[request.payment_id]
    payment["status"] = "refunded"
    payment["refund_reason"] = request.reason
    payment["refunded_at"] = datetime.now().isoformat()

    logger.info(
        "Refund processed for payment %s: €%.2f",
        request.payment_id,
        payment["amount"],
    )

    return {
        "payment_id": request.payment_id,
        "status": "refunded",
        "amount": payment["amount"],
        "message": "Refund processed successfully",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)