from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.taxonomy import SkillTaxonomyLoader
from app.services.parser import CVParserService, build_parser_service
from app.services.scorer import ScorerService
from app.services.skill_matcher import SkillMatcherService


def _to_async_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_to_async_database_url(settings.database_url), echo=settings.debug, future=True)
AsyncSessionFactory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

taxonomy_loader = SkillTaxonomyLoader("data/taxonomy/skill_taxonomy.yaml")
taxonomy_loader.load()
skill_matcher = SkillMatcherService(taxonomy_loader)
scorer_service = ScorerService(skill_matcher)
parser_service = build_parser_service()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        yield session


def get_parser_service() -> CVParserService:
    return parser_service


def get_scorer_service() -> ScorerService:
    return scorer_service


def get_skill_matcher_service() -> SkillMatcherService:
    return skill_matcher
