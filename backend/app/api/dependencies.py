from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.taxonomy import SkillTaxonomyLoader
from app.services.cv_parser import CVParserService, build_cv_parser_service
from app.services.jd_parser import JDParserService, build_jd_parser_service
from app.services.scorer import ScorerService
from app.services.skill_matcher import SkillMatcherService


def _to_async_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(
    _to_async_database_url(settings.database_url),
    echo=settings.debug,
    future=True,
    pool_pre_ping=True,
)
AsyncSessionFactory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

taxonomy_loader = SkillTaxonomyLoader("data/taxonomy/skill_taxonomy.yaml")
taxonomy_loader.load()
skill_matcher = SkillMatcherService(taxonomy_loader)
scorer_service = ScorerService(skill_matcher)
cv_parser_service = build_cv_parser_service()
jd_parser_service = build_jd_parser_service(taxonomy_loader=taxonomy_loader)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        yield session


def get_cv_parser_service() -> CVParserService:
    return cv_parser_service


def get_parser_service() -> CVParserService:
    """Backward-compatible alias for existing dependency injection."""
    return get_cv_parser_service()


def get_jd_parser_service() -> JDParserService:
    return jd_parser_service


def get_scorer_service() -> ScorerService:
    return scorer_service


def get_skill_matcher_service() -> SkillMatcherService:
    return skill_matcher
