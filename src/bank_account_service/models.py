"""ORM-моделі SQLAlchemy: clients 1–N accounts 1–N transactions."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, MetaData, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

CENT = Decimal("0.01")

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


class Cents(TypeDecorator[Decimal]):
    """Decimal у Python <-> ціле число копійок у БД.

    SQLite не має точного DECIMAL: NUMERIC зберігається як REAL (float) з похибками.
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        cents = value / CENT
        if cents != cents.to_integral_value():
            raise ValueError(f"сума {value} має більше двох знаків після коми")
        return int(cents)

    def process_result_value(self, value: Any | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(int(value)) * CENT


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (CheckConstraint("length(trim(full_name)) > 0", name="name_not_blank"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))

    accounts: Mapped[list["Account"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Account.number",
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance_cents >= 0", name="balance_not_negative"),
        CheckConstraint("length(currency) = 3", name="currency_code"),
        CheckConstraint("account_type IN ('current', 'savings')", name="known_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(11), unique=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    balance: Mapped[Decimal] = mapped_column("balance_cents", Cents)
    account_type: Mapped[str] = mapped_column(
        String(10), default="current", server_default="current"
    )
    version: Mapped[int] = mapped_column(Integer)

    client: Mapped[Client] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Transaction.id",
    )

    __mapper_args__ = {"version_id_col": version}


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint("balance_after_cents >= 0", name="balance_after_not_negative"),
        CheckConstraint(
            "operation IN ('deposit', 'withdraw', 'transfer_in', 'transfer_out')",
            name="known_operation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column("amount_cents", Cents)
    balance_after: Mapped[Decimal] = mapped_column("balance_after_cents", Cents)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    account: Mapped[Account] = relationship(back_populates="transactions")
