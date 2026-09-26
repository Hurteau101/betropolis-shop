import asyncio
import decimal
import os
from datetime import datetime, UTC
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, URL, DateTime, ForeignKey, select, BigInteger, BIGINT, Numeric, update, delete
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio.engine import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, joinedload
from dotenv import load_dotenv
load_dotenv()


def _url(production: bool, driver: str):
    return URL.create(
        driver,
        username=os.getenv('DB_USER'),
        password=os.getenv('DB_PASS'),
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        database=os.getenv('DB_NAME_PROD') if production else os.getenv('DB_NAME_TEST'),
    )

def is_production():
    return os.getenv("IS_PRODUCTION", '').lower() == "true"

def async_engine():
    production = is_production()
    return create_async_engine(
        _url(production, "postgresql+asyncpg"),
        echo=not production,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

def async_session_maker():
    return async_sessionmaker(async_engine(), expire_on_commit=False)

Session = async_session_maker()

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    created_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    balance: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), default=0)
    orders: Mapped[list["Order"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @classmethod
    async def add_tokens(cls, db_session: AsyncSession, user_id: int, amount: decimal.Decimal | float | int):
        if isinstance(amount, (int, float)):
            amount = decimal.Decimal(str(amount))

        stmt = (
            update(User)
            .where(User.user_id == user_id)
            .values(balance=User.balance + amount)
            .returning(User)
        )

        result = await db_session.execute(stmt)
        await db_session.commit()

        return result.scalar_one_or_none()

    @classmethod
    async def subtract_tokens(cls, db_session: AsyncSession, user_id: int, amount: decimal.Decimal | float | int, should_commit: bool = True):
        if isinstance(amount, (int, float)):
            amount = decimal.Decimal(str(amount))

        stmt = (
            update(User)
            .where(User.user_id == user_id, User.balance >= amount)
            .values(balance=User.balance - amount)
            .returning(User)
        )

        result = await db_session.execute(stmt)
        user_account = result.scalar_one_or_none()

        if user_account is None:  # Insufficient funds
            await db_session.rollback()
            return None

        if should_commit:
            await db_session.commit()

        return user_account


    @classmethod
    async def get_users(cls, db_session: AsyncSession):
        result = await db_session.execute(select(cls.user_id))
        return [row[0] for row in result.all()]

    @classmethod
    async def get_user(cls, db_session: AsyncSession, user_id: int):
        result = await db_session.execute(select(cls).where(user_id == cls.user_id))
        return result.scalar()

    @classmethod
    async def bulk_add_users(cls, db_session: AsyncSession, users: list[int]):
        insert_smt = insert(User).values(users)
        do_update = insert_smt.on_conflict_do_nothing(
            index_elements=["user_id"]
        )

        await db_session.execute(do_update)
        await db_session.commit()

    @classmethod
    async def add_user(cls, db_session: AsyncSession, user_id: int):
        stmt = insert(User).values(user_id=user_id)
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id"])
        result = await db_session.execute(stmt)
        await db_session.commit()
        return result.rowcount > 0

    @classmethod
    async def get_user_orders(cls, db_session: AsyncSession, user_id: int, open_orders_only: bool = False):
        stmt = select(Order).where(Order.user_id == user_id).options(selectinload(Order.product))

        if open_orders_only:
            stmt = stmt.where(Order.completed.is_(False), Order.order_rejected.is_(False))

        result = await db_session.execute(stmt)
        return result.scalars().all()


class Product(Base):
    __tablename__ = "products"
    product_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    description: Mapped[str] = mapped_column()
    tags: Mapped[str] = mapped_column()
    price: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    stock: Mapped[int] = mapped_column()
    thread_id: Mapped[int] = mapped_column(BigInteger)
    orders: Mapped[list["Order"]] = relationship(back_populates="product")

    @classmethod
    async def find_product_by_thread_id(cls, db_session: AsyncSession, thread_id: int):
        result = await db_session.execute(select(cls).where(cls.thread_id == thread_id))
        return result.scalar_one_or_none()

    @classmethod
    async def delete_product(cls, db_session: AsyncSession, thread_id: int):
        result = await db_session.execute(delete(cls).where(cls.thread_id == thread_id))
        await db_session.commit()
        return result.rowcount > 0


    @classmethod
    async def add_product(cls, db_session: AsyncSession, name: str, price: int | float | decimal.Decimal, stock: int, thread_id: int,
                          description: str, tags: str):
        if isinstance(price, (int, float)):
            price = decimal.Decimal(str(price))

        product = cls(name=name, price=price, stock=stock, thread_id=thread_id, description=description, tags=tags)
        db_session.add(product)
        await db_session.commit()
        return product.product_id

    @classmethod
    async def update_product(cls, db_session: AsyncSession, product_id: int, name: str,
                             price: int | float | decimal.Decimal, stock: int, thread_id: int,
                             description: str, tags: str):
        if isinstance(price, (int, float)):
            price = decimal.Decimal(str(price))

        stmt = (
            update(Product)
            .where(Product.product_id == product_id)
            .values(
                name=name,
                price=price,
                stock=stock,
                thread_id=thread_id,
                description=description,
                tags=tags,
            )
            .returning(Product)
        )

        result = await db_session.execute(stmt)
        await db_session.commit()

        return result.scalar_one_or_none()

    @classmethod
    async def get_product(cls, db_session: AsyncSession, product_id: int):
        result = await db_session.execute(select(cls).where(cls.product_id == product_id))
        return result.scalar()

    @classmethod
    async def reduce_stock(cls, db_session: AsyncSession, product_id: int):
        stmt = (
            update(Product)
            .where(Product.product_id == product_id, Product.stock >= 1)
            .values(stock=Product.stock - 1)
            .returning(Product)
        )

        result = await db_session.execute(stmt)
        product = result.scalar_one_or_none()

        if product is None: # Not enough stock
            return None

        return product


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    user: Mapped[User] = relationship(back_populates="orders")
    channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    completed_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    completed: Mapped[bool] = mapped_column(default=False)
    completed_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id", ondelete="CASCADE"))
    product: Mapped[Product] = relationship(back_populates="orders")
    order_rejected: Mapped[bool] = mapped_column(default=False)
    order_rejected_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    order_reject_reason: Mapped[str | None] = mapped_column(default=None)
    order_cancelled: Mapped[bool] = mapped_column(default=False)
    order_cancelled_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @classmethod
    async def delete_order(cls, db_session: AsyncSession, order_id: int):
        stmt = delete(Order).where(Order.id == order_id)
        result = await db_session.execute(stmt)
        await db_session.commit()
        return result.rowcount > 0

    @classmethod
    async def cancel_order(cls, db_session: AsyncSession, order_id: int):
        current_date = datetime.now(UTC)
        stmt = (
            update(Order)
            .where(Order.id == order_id, Order.completed == False, Order.order_rejected == False)
            .values(order_cancelled=True, order_cancelled_date=current_date)
            .returning(Order)
            .options(selectinload(Order.product))
        )

        result = await db_session.execute(stmt)
        await db_session.commit()
        return result.scalar_one_or_none()

    @classmethod
    async def add_order(cls, db_session: AsyncSession, user_id: int, product_id: int, should_commit: bool = True):
        order = cls(user_id=user_id, product_id=product_id)
        db_session.add(order)

        if should_commit:
            await db_session.commit()
        else:
            await db_session.flush()

        return order

    @classmethod
    async def find_order(cls, db_session: AsyncSession, order_id: int):
        result = await db_session.execute(select(cls).where(cls.id == order_id))
        return result.scalar_one_or_none()

    @classmethod
    async def update_order(cls, db_session: AsyncSession, order_id: int, completed: bool, completed_by: int = None,
                           is_rejected: bool = False, rejected_by: int = None, reject_reason: str = None,
                           auto_commit: bool = False):
        current_date = datetime.now(UTC)

        stmt = (
            update(Order)
            .where(Order.id == order_id, Order.completed == False, Order.order_rejected == False, Order.order_cancelled == False)
            .values(completed=completed)
            .returning(Order)
            .options(selectinload(Order.product))
        )

        if completed:
            stmt = stmt.values(
                completed_by=completed_by,
                completed_date=current_date,
            )

        if is_rejected and all([rejected_by, reject_reason]):
            stmt = stmt.values(
                order_rejected=True,
                order_rejected_by=rejected_by,
                order_reject_reason=reject_reason,
            )

        result = await db_session.execute(stmt)

        if auto_commit:
            await db_session.commit()

        return result.scalar_one_or_none()

    @classmethod
    async def find_by_channel(cls, db_session: AsyncSession, channel_id: int):
        result = await db_session.execute(select(cls).where(cls.channel_id == channel_id))
        return result.scalar_one_or_none()

if __name__ == "__main__":
    if __name__ == "__main__":
        async def main():
            engine = async_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await engine.dispose()




        asyncio.run(main())