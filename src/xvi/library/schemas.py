from typing import Literal

from pydantic import BaseModel, Field

ReviewStatus = Literal["accepted", "rejected", "needs_review"]
DeliveryStatus = Literal["new", "delivered"]


class AssetReviewUpdate(BaseModel):
    status: ReviewStatus
    reviewer: str = Field(default="网页复核", min_length=1, max_length=80)
    reason: str | None = Field(default=None, max_length=500)


class DeliveryUpdate(BaseModel):
    status: DeliveryStatus
