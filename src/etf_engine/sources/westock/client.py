import glob
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


class WestockClient:
    """WeStock (westock-data-clawhub) CLI 客户端封装。

    支持调用底层 npm 工具包执行 ETF 数据查询，并将 Markdown 表格输出结构化为 Python 字典列表。
    """

    def __init__(self, script_path: str | None = None, timeout: int = 30):
        self.timeout = timeout
        self._script_path = script_path or self._detect_cached_script()

    def _detect_cached_script(self) -> str | None:
        """优先探测 ~/.npm/_npx/**/westock-data-clawhub/scripts/index.js，避免每次 npx 解析网络开销。"""
        home = Path.home()
        pattern = str(home / ".npm" / "_npx" / "**" / "westock-data-clawhub" / "scripts" / "index.js")
        matches = glob.glob(pattern, recursive=True)
        return matches[0] if matches else None

    def execute(self, command: str, *args: str) -> str:
        """执行指定命令并返回原始标准输出。"""
        node_bin = shutil.which("node")
        if self._script_path and node_bin and os.path.exists(self._script_path):
            cmd = [node_bin, self._script_path, command, *args]
        else:
            npx_bin = shutil.which("npx") or "npx"
            cmd = [npx_bin, "-y", "westock-data-clawhub@1.0.4", command, *args]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"WeStock 命令超时 ({self.timeout}s): {' '.join(cmd)}") from exc

        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip()
            raise RuntimeError(f"WeStock 命令执行失败: {err_msg}")

        return res.stdout

    @staticmethod
    def parse_markdown_table(markdown_text: str) -> list[dict[str, str]]:
        """从一段包含单个 Markdown 表格的文本中提取行数据为字典列表。"""
        lines = [line.strip() for line in markdown_text.splitlines() if line.strip().startswith("|")]
        if len(lines) < 3:
            return []

        headers = [c.strip() for c in lines[0].strip("|").split("|")]
        data: list[dict[str, str]] = []
        for row_line in lines[2:]:
            cells = [c.strip() for c in row_line.strip("|").split("|")]
            if len(cells) == len(headers):
                data.append(dict(zip(headers, cells, strict=True)))
        return data

    @classmethod
    def parse_etf_details(cls, output: str) -> dict[str, Any]:
        """解析 ``westock-data etf <symbol>`` 的完整输出。

        包含：
        - 'info': ETF 核心指标字典 (最新行情/份额/规模/跟踪指数)
        - 'holdings': Top20 持仓明细列表
        - 'manager': 基金经理信息
        - 'prlist_date': 清单/披露日期
        """
        result: dict[str, Any] = {
            "info": {},
            "holdings": [],
            "manager": {},
        }

        # 区分各个标题段落
        sections = re.split(r"(?:\n|^)(?:####|\*\*)\s*", output)
        for sec in sections:
            sec_strip = sec.strip()
            if not sec_strip:
                continue

            if "持仓明细" in sec_strip:
                result["holdings"] = cls.parse_markdown_table(sec_strip)
            elif "基金经理" in sec_strip:
                mgr_rows = cls.parse_markdown_table(sec_strip)
                if mgr_rows:
                    result["manager"] = mgr_rows[0]
            elif "code" in sec_strip and "name" in sec_strip and "|" in sec_strip:
                info_rows = cls.parse_markdown_table(sec_strip)
                if info_rows:
                    result["info"] = info_rows[0]

        return result

    @classmethod
    def parse_holdings(cls, output: str) -> tuple[list[dict[str, str]], str | None]:
        """解析 ``westock-data etf-holdings <symbol>`` 的输出。

        返回: (holdings_rows, disclosure_date_str)
        """
        # 匹配标题里的日期: (清单日期: 2026-09-14 00:00:00 +0800 CST)
        date_match = re.search(r"清单日期:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", output)
        disclosure_date = date_match.group(1) if date_match else None
        holdings = cls.parse_markdown_table(output)
        return holdings, disclosure_date
