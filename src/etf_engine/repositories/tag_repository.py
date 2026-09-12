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
                )
            )

        sql = """
        INSERT INTO core.etf_tag (
            etf_id, tag, tag_type, confidence, source, valid_from, valid_to
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (etf_id, tag, tag_type, valid_from) DO UPDATE SET
            confidence = EXCLUDED.confidence,
            source = EXCLUDED.source,
            valid_to = EXCLUDED.valid_to
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def get_tags(self, etf_id: str) -> list[dict]:
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT tag, tag_type, confidence FROM core.etf_tag
                WHERE etf_id = ? ORDER BY confidence DESC
                """,
                [etf_id],
            ).fetchall()
            cols = [c[0] for c in con.description]
            return [dict(zip(cols, r, strict=True)) for r in rows]
