from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import StockIndustry


class StockIndustryRepository:
    def upsert_many(self, records: list[StockIndustry]) -> int:
        if not records:
            return 0

        rows = [
            (
                record.stock_id,
                record.stock_name,
                record.industry_name,
                record.industry_code,
                record.classification_standard,
                record.source_meta.source,
                record.source_meta.fetched_at,
            )
            for record in records
        ]
        sql = """
        INSERT INTO core.stock_industry (
            stock_id, stock_name, industry_name, industry_code,
            classification_standard, source, fetched_at
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (stock_id) DO UPDATE SET
            stock_name = COALESCE(EXCLUDED.stock_name, core.stock_industry.stock_name),
            industry_name = EXCLUDED.industry_name,
            industry_code = COALESCE(EXCLUDED.industry_code, core.stock_industry.industry_code),
            classification_standard = EXCLUDED.classification_standard,
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def industry_map(self) -> dict[str, str]:
        """返回 ``{security_id: industry_name}``。"""
        with connect(settings.database_path) as con:
            rows = con.execute("SELECT stock_id, industry_name FROM core.stock_industry").fetchall()
        return {stock_id: industry for stock_id, industry in rows}

    def count(self) -> int:
        with connect(settings.database_path) as con:
            return int(con.execute("SELECT count(*) FROM core.stock_industry").fetchone()[0])
