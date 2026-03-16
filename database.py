from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from config import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def init_db():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("✓ MySQL connected to sql113.cpanelfree.com")
    except Exception as e:
        logger.error(f"✗ DB connection failed: {e}")
        raise


async def setting(db: AsyncSession, key: str, default: str = "") -> str:
    """Get one setting value from DB."""
    r = await db.execute(text("SELECT `value` FROM settings WHERE `key`=:k"), {"k": key})
    row = r.fetchone()
    return row[0] if row else default


async def all_settings(db: AsyncSession) -> dict:
    """Get all settings as dict."""
    r = await db.execute(text("SELECT `key`,`value` FROM settings"))
    return {row[0]: row[1] for row in r.fetchall()}


async def public_settings(db: AsyncSession) -> dict:
    """Get public settings (safe to expose to frontend)."""
    r = await db.execute(text("SELECT `key`,`value` FROM settings WHERE is_public=1"))
    return {row[0]: row[1] for row in r.fetchall()}
