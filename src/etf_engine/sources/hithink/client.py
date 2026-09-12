from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class HiThinkClient:
    api_key: str
    base_url: str = "https://fuyao.aicubes.cn"

    def _headers(self) -> dict[str, str]:
        return {"X-api-key": self.api_key}

    def get(self, path: str, params: dict | None = None) -> dict:
        with httpx.Client(base_url=self.base_url, timeout=20.0) as client:
            response = client.get(path, params=params, headers=self._headers())
            response.raise_for_status()
            payload = response.json()

        if payload.get("code") != 0:
            raise RuntimeError(
                f"HiThink business error code={payload.get('code')} "
                f"message={payload.get('message')} request_id={payload.get('request_id')}"
            )
        data = payload["data"]
        if not isinstance(data, dict):
            raise RuntimeError("HiThink response data must be an object")
        return data
