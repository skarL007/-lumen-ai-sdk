"""
The public event payload (schema.event_types.LumenAIEvent, a TypedDict) and the
ORM row class shared the name LumenAIEvent, which is confusing and collision-prone
for importers. The ORM class is renamed LumenAIEventRow; the TypedDict is unchanged.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)


def test_orm_row_renamed_and_mappers_resolve():
    import lumen_ai.models as models
    from sqlalchemy.orm import configure_mappers

    assert hasattr(models, "LumenAIEventRow")
    assert models.LumenAIEventRow.__tablename__ == "LumenAI_events"
    assert not hasattr(models, "LumenAIEvent")  # no ambiguous ORM/TypedDict clash
    # Relationship strings must still resolve to the renamed class.
    configure_mappers()


def test_public_typeddict_unchanged():
    from lumen_ai.schema.event_types import LumenAIEvent

    assert "tenant_id" in LumenAIEvent.__annotations__
    assert "cost_usd" in LumenAIEvent.__annotations__
