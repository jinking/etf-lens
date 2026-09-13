from datetime import datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import ETFMaster


class MasterRepository:
    def upsert_many(self, masters: list[ETFMaster]) -> int:
        if not masters:
            return 0

        rows = []
        now = datetime.now().astimezone()
        for m in masters:
            rows.append(
                (
                    m.security_id,
                    m.ticker,
                    m.exchange,
                    m.fund_name,
                    m.short_name,
                    m.fund_type,
                    m.investment_type,
                    m.manager_name,
                    m.custodian_name,
                    m.established_date,
                    m.listed_date,
                    m.tracking_index_id,
                    m.tracking_index_name,
                    float(m.reported_aum) if m.reported_aum is not None else None,
                    m.reported_aum_date,
                    m.asset_region,
                    m.base_currency,
                    m.tracking_index_currency,
                    m.is_cross_border,
                    float(m.management_fee_pct) if m.management_fee_pct is not None else None,
                    float(m.custodian_fee_pct) if m.custodian_fee_pct is not None else None,
                    m.status,
                    m.source_meta.source,
                    m.source_meta.fetched_at,
                    now,
                )
            )

        sql = """
        INSERT INTO core.etf_master (
            security_id, ticker, exchange, fund_name, short_name, fund_type,
            investment_type, manager_name, custodian_name, established_date,
            listed_date, tracking_index_id, tracking_index_name, reported_aum,
            reported_aum_date, asset_region, base_currency, tracking_index_currency,
            is_cross_border, management_fee_pct, custodian_fee_pct, status,
            source, source_updated_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id) DO UPDATE SET
            ticker = EXCLUDED.ticker,
            exchange = EXCLUDED.exchange,
            fund_name = COALESCE(EXCLUDED.fund_name, core.etf_master.fund_name),
            short_name = COALESCE(EXCLUDED.short_name, core.etf_master.short_name),
            fund_type = COALESCE(EXCLUDED.fund_type, core.etf_master.fund_type),
            investment_type = COALESCE(
                EXCLUDED.investment_type, core.etf_master.investment_type
            ),
            manager_name = COALESCE(EXCLUDED.manager_name, core.etf_master.manager_name),
            custodian_name = COALESCE(EXCLUDED.custodian_name, core.etf_master.custodian_name),
            established_date = COALESCE(
                EXCLUDED.established_date, core.etf_master.established_date
            ),
            listed_date = COALESCE(EXCLUDED.listed_date, core.etf_master.listed_date),
            tracking_index_id = COALESCE(
                EXCLUDED.tracking_index_id, core.etf_master.tracking_index_id
            ),
            tracking_index_name = COALESCE(
                EXCLUDED.tracking_index_name, core.etf_master.tracking_index_name
            ),
            reported_aum = COALESCE(EXCLUDED.reported_aum, core.etf_master.reported_aum),
            reported_aum_date = COALESCE(
                EXCLUDED.reported_aum_date, core.etf_master.reported_aum_date
            ),
            asset_region = COALESCE(EXCLUDED.asset_region, core.etf_master.asset_region),
            base_currency = COALESCE(EXCLUDED.base_currency, core.etf_master.base_currency),
            tracking_index_currency = COALESCE(
                EXCLUDED.tracking_index_currency, core.etf_master.tracking_index_currency
            ),
            is_cross_border = EXCLUDED.is_cross_border,
            management_fee_pct = COALESCE(
                EXCLUDED.management_fee_pct, core.etf_master.management_fee_pct
            ),
            custodian_fee_pct = COALESCE(
                EXCLUDED.custodian_fee_pct, core.etf_master.custodian_fee_pct
            ),
            status = EXCLUDED.status,
            source = EXCLUDED.source,
            source_updated_at = EXCLUDED.source_updated_at,
            updated_at = EXCLUDED.updated_at
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def get_by_id(self, security_id: str) -> dict | None:
        with connect(settings.database_path) as con:
            row = con.execute(
                "SELECT * FROM core.etf_master WHERE security_id = ?", [security_id]
            ).fetchone()
            if row is None:
                return None
            columns = [c[0] for c in con.description]
            return dict(zip(columns, row, strict=True))

    def count(self) -> int:
        with connect(settings.database_path) as con:
            return int(con.execute("SELECT count(*) FROM core.etf_master").fetchone()[0])

    def enrich_from_profile(self, profiles: list) -> int:
        """用基金档案补齐 master 的空字段。

        只补空（``COALESCE``）：档案是"静态披露事实"，不覆盖行情源写过的字段，
        也不改写 ``source``（那是抓取来源的溯源字段，档案不是它的事实来源）。
        """
        if not profiles:
            return 0

        rows = [
            (
                profile.fund_name,
                profile.short_name,
                profile.fund_type,
                profile.established_date,
                profile.manager_name,
                profile.custodian_name,
                float(profile.management_fee_pct)
                if profile.management_fee_pct is not None
                else None,
                float(profile.custodian_fee_pct) if profile.custodian_fee_pct is not None else None,
                profile.tracking_target,
                profile.source_meta.fetched_at,
                profile.security_id,
            )
            for profile in profiles
        ]
        sql = """
        UPDATE core.etf_master SET
            fund_name = COALESCE(fund_name, ?),
            short_name = COALESCE(short_name, ?),
            fund_type = COALESCE(fund_type, ?),
            established_date = COALESCE(established_date, ?),
            manager_name = COALESCE(manager_name, ?),
            custodian_name = COALESCE(custodian_name, ?),
            management_fee_pct = COALESCE(management_fee_pct, ?),
            custodian_fee_pct = COALESCE(custodian_fee_pct, ?),
            tracking_index_name = COALESCE(tracking_index_name, ?),
            -- 档案观测时间：只在首次补齐档案时写上。历史查询据此判定
            -- profile_observed_at <= asof，否则该字段对它不可用（V2.1 §13）。
            profile_observed_at = COALESCE(profile_observed_at, ?),
            updated_at = now()
        WHERE security_id = ?
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)
