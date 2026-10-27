import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from sqlalchemy import ForeignKeyConstraint

from lumen_ai.models import LumenAIAgent, LumenAIArtifact, LumenAIEventRow, LumenAISession


def _constraint_columns(table, name):
    for constraint in table.constraints:
        if constraint.name == name:
            return tuple(column.name for column in constraint.columns)
    return ()


def test_parent_tables_have_tenant_id_unique_keys_for_composite_fks():
    assert _constraint_columns(
        LumenAISession.__table__, "uq_LumenAI_sessions_tenant_id"
    ) == ("tenant_id", "id")
    assert _constraint_columns(
        LumenAIAgent.__table__, "uq_LumenAI_agents_tenant_id"
    ) == ("tenant_id", "id")


def test_child_tables_use_tenant_scoped_foreign_keys():
    fk_names = {
        constraint.name
        for table in (LumenAIAgent.__table__, LumenAIEventRow.__table__, LumenAIArtifact.__table__)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert "fk_LumenAI_agents_tenant_session" in fk_names
    assert "fk_LumenAI_events_tenant_session" in fk_names
    assert "fk_LumenAI_events_tenant_agent" in fk_names
    assert "fk_LumenAI_artifacts_tenant_session" in fk_names
    assert "fk_LumenAI_artifacts_tenant_agent" in fk_names
