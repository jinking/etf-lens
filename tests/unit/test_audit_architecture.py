"""架构自检必须"能被触发"，否则只是装饰。

两个方向都要测：

* 在真实的 ``src/etf_engine`` 上必须**零违规**（回归守卫——以后谁把 akshare
  import 到 service 里，这个测试立刻红）；
* 在临时目录里造出违规代码，检查器必须抓到（否则规则可能已经失效）。
"""

import textwrap
from pathlib import Path

from etf_engine.audit.architecture import (
    REQUIRED_CAPABILITY_INTERFACES,
    check_architecture,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "etf_engine"


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def _base_sources(root: Path) -> None:
    """最小可用的包骨架（含能力接口，避免干扰其它规则）。"""
    body = "\n".join(
        f"class {name}:\n    pass\n" for name in REQUIRED_CAPABILITY_INTERFACES
    )
    _write(root, "sources/base.py", body)
    _write(root, "sources/__init__.py", "")


def test_real_package_has_no_architecture_violations():
    assert check_architecture(PACKAGE_ROOT) == []


def test_business_layer_cannot_import_akshare(tmp_path):
    _base_sources(tmp_path)
    _write(
        tmp_path,
        "services/bad_service.py",
        """
        import akshare as ak

        def fetch():
            return ak.fund_etf_spot_em()
        """,
    )

    violations = check_architecture(tmp_path)

    assert [item.rule for item in violations] == [
        "no_third_party_finance_in_business_layers"
    ]
    assert "akshare" in violations[0].detail


def test_sources_layer_may_import_akshare(tmp_path):
    _base_sources(tmp_path)
    _write(
        tmp_path,
        "sources/akshare/quotes.py",
        """
        import akshare as ak
        """,
    )

    assert check_architecture(tmp_path) == []


def test_research_cannot_depend_on_sources(tmp_path):
    _base_sources(tmp_path)
    _write(
        tmp_path,
        "research/bad.py",
        """
        from etf_engine.sources.registry import registry
        """,
    )

    violations = check_architecture(tmp_path)

    assert [item.rule for item in violations] == ["respect_dependency_direction"]
    assert "sources" in violations[0].detail


def test_domain_cannot_depend_on_anything_upper(tmp_path):
    _base_sources(tmp_path)
    _write(
        tmp_path,
        "domain/bad.py",
        """
        from etf_engine.services.etf_service import ETFService
        """,
    )

    violations = check_architecture(tmp_path)

    assert [item.rule for item in violations] == ["respect_dependency_direction"]


def test_missing_capability_interface_is_reported(tmp_path):
    _base_sources(tmp_path)
    # 删掉一个能力接口
    base = (tmp_path / "sources" / "base.py").read_text(encoding="utf-8")
    (tmp_path / "sources" / "base.py").write_text(
        base.replace(f"class {REQUIRED_CAPABILITY_INTERFACES[0]}:\n    pass\n", ""),
        encoding="utf-8",
    )

    violations = check_architecture(tmp_path)

    assert [item.rule for item in violations] == ["capability_interfaces_present"]
    assert REQUIRED_CAPABILITY_INTERFACES[0] in violations[0].detail
