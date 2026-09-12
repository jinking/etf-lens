from etf_engine.domain.identifiers import SecurityId
from etf_engine.repositories.quote_repository import QuoteRepository


class ETFService:
    def __init__(self, quote_repository: QuoteRepository | None = None):
        self.quotes = quote_repository or QuoteRepository()

    def get_latest_snapshot(self, security_id: str) -> dict:
        canonical = SecurityId.parse(security_id).value
        quote = self.quotes.get_latest(canonical)
        return {
            "security_id": canonical,
            "quote": quote,
        }

    def search_etfs(self, query: str | None = None, limit: int = 20) -> list[dict]:
        return self.quotes.search_latest(query=query, limit=limit)

    def dashboard_summary(self) -> dict:
        return self.quotes.dashboard_summary()
