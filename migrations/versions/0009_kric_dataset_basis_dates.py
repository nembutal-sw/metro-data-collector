"""Correct KRIC metadata and versions to workbook data-basis dates.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry source
        SET metadata=jsonb_set(source.metadata, '{dataset_as_of}', to_jsonb(input.basis))
        FROM (VALUES
            ('UI_SINSEOL_WEB', '2022-05-30'::text),
            ('UIJEONGBU_WEB', '2023-09-06'::text),
            ('SILLIM_WEB', '2025-09-23'::text),
            ('GIMPO_GOLD_WEB', '2026-06-16'::text)
        ) AS input(code, basis)
        WHERE source.code=input.code;

        UPDATE timetable_version version
        SET effective_from=input.basis
        FROM source_registry source,
             (VALUES
                ('UI_SINSEOL_WEB', DATE '2022-05-30'),
                ('UIJEONGBU_WEB', DATE '2023-09-06'),
                ('SILLIM_WEB', DATE '2025-09-23'),
                ('GIMPO_GOLD_WEB', DATE '2026-06-16')
             ) AS input(code, basis)
        WHERE version.source_id=source.id AND source.code=input.code;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry source
        SET metadata=jsonb_set(source.metadata, '{dataset_as_of}', to_jsonb(input.basis))
        FROM (VALUES
            ('UI_SINSEOL_WEB', '2023-01-06'::text),
            ('UIJEONGBU_WEB', '2023-09-04'::text),
            ('SILLIM_WEB', '2025-09-30'::text),
            ('GIMPO_GOLD_WEB', '2026-06-30'::text)
        ) AS input(code, basis)
        WHERE source.code=input.code;
        """
    )
