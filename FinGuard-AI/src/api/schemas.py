"""Request models: strict validation (length, format, ranges)."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class DateRange(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def check(self):
        if self.end < self.start:
            raise ValueError("end must be on or after start")
        if (self.end - self.start).days > 120:
            raise ValueError("date range must be at most 120 days")
        return self


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    date_range: DateRange
    use_llm: bool = False


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    date_range: Optional[DateRange] = None
    use_llm: bool = False


class PolicySearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    k: int = Field(default=3, ge=1, le=10)


class PredictRequest(BaseModel):
    amount: float = Field(ge=0, le=10_000_000)
    timestamp: datetime
    merchant_category: str = Field(pattern=r"^[a-z_]{2,30}$")
    country: str = Field(pattern=r"^[A-Z]{2}$")
    home_country: str = Field(pattern=r"^[A-Z]{2}$")
    channel: str = Field(pattern=r"^[A-Za-z_]{2,20}$")
    device_type: str = Field(pattern=r"^[a-z_]{2,10}$")


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)