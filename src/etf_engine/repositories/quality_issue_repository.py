from datetime import date, datetime
from uuid import uuid4

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.quality import DataQualityIssue


class QualityIssueRepository:
    """把解析/校验/对账发现的问题落到 ``ops.quality_issue``。

    ``docs/TECHNICAL.md`` §5 要求异常数据不静默删除；历史实现里
    validator 的结果只被用来计数后丢弃，这张表一直是空的。
    """

    def record(
        self,
        *,
        dataset: str,
        issues: list[DataQualityIssue],
        security_id: str | None = None,
        trade_date: date | None = None,
    ) -> int:
        if not issues:
            return 0

        created_at = datetime.now().astimezone()
        rows = [
            (
                uuid4().hex,
                dataset,
                security_id,
                trade_date,
                issue.severity,
                issue.rule_name,
                issue.details,
                created_at,
            )
            for issue in issues
        ]
        sql = """
        INSERT INTO ops.quality_issue (
            issue_id, dataset, security_id, trade_date, severity,
            rule_name, details, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def count(self) -> int:
        with connect(settings.database_path) as con:
            return int(con.execute("SELECT count(*) FROM ops.quality_issue").fetchone()[0])
