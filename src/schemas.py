"""Pydantic request/response models for OptionLedger API."""

from datetime import date
from pydantic import BaseModel
from typing import List, Optional


class SyncRequest(BaseModel):
    days_back: int = 30


class TradeFilter(BaseModel):
    status: Optional[str] = None
    strategy: Optional[str] = None
    underlying: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    search_term: Optional[str] = None


class StrategyTarget(BaseModel):
    strategy_name: str
    profit_target_pct: float
    loss_target_pct: float


class OrderCommentUpdate(BaseModel):
    comment: str


class PositionNoteUpdate(BaseModel):
    note: str


class LedgerGroupUpdate(BaseModel):
    strategy_label: Optional[str] = None


class LedgerMoveLots(BaseModel):
    transaction_ids: List[str]
    target_group_id: str


class LedgerCreateGroup(BaseModel):
    account_number: str
    underlying: str
    strategy_label: Optional[str] = None


class CredentialUpdate(BaseModel):
    provider_secret: str
    refresh_token: str
