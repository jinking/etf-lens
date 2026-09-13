from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect


class TagRepository:
    def upsert_tags(self, records: list[dict]) -> int:
        if not records:
            return 0

        rows = []
        for r in records:
            rows.append(
                (
                    r["etf_id"],
                    r["tag"],
                    r.get("tag_type", "industry"),
                    float(r.get("confidence", 1.0)),
                    r.get("source", "holding_penetration"),
                    r.get("valid_from"),
                    r.get("valid_to"),
                    r.get("calculation_version"),
                    r.get("coverage"),
                )
            )

        sql = """
        INSERT INTO core.etf_tag (
            etf_id, tag, tag_type, confidence, source, valid_from, valid_to,
            calculation_version, coverage
        ) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT (etf_id, tag, tag_type, valid_from) DO UPDATE SET
            confidence = EXCLUDED.confidence,
            source = EXCLUDED.source,
            valid_to = EXCLUDED.valid_to,
            calculation_version = EXCLUDED.calculation_version,
            coverage = EXCLUDED.coverage
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def get_tags(self, etf_id: str) -> list[dict]:
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT tag, tag_type, confidence, coverage, calculation_version
                FROM core.etf_tag
                WHERE etf_id = ? ORDER BY confidence DESC
                """,
                [etf_id],
            ).fetchall()
            cols = [c[0] for c in con.description]
            return [dict(zip(cols, r, strict=True)) for r in rows]

    def get_tags_asof(self, etf_id: str, asof_date: date) -> list[dict]:
        """Point-in-Time 版标签：``valid_from <= asof < valid_to``。

        不能只按 ``etf_id`` 取"今天的标签"——那会把后来才打上的行业标签
        灌进历史研究（例如拿 2026 年的持仓穿透结果解释 2025 年的 ETF）。
        """
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT tag, tag_type, confidence, coverage, calculation_version,
                       valid_from, valid_to
                FROM core.etf_tag
                WHERE etf_id = ?
                  AND (valid_from IS NULL OR valid_from <= ?)
                  AND (valid_to IS NULL OR valid_to > ?)
                ORDER BY confidence DESC
                """,
                [etf_id, asof_date, asof_date],
            ).fetchall()
            cols = [c[0] for c in con.description]
            return [dict(zip(cols, r, strict=True)) for r in rows]
