from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_doctor_reports_dependency_health():
    from aphrodite.doctor import doctor_payload

    deps = doctor_payload()["dependencies"]
    assert deps["ok"] is True
    assert "fastapi" in deps["installed"]
    assert deps["missing"] == []
    assert "sandbox" in deps["note"]
    assert deps["below_floor"] == {}
    assert deps["version_check"] == "active"


def test_security_md_documents_adapter_model():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Adapter security model" in text
    assert "APHRODITE_TRUSTED_ADAPTERS" in text
    assert "APHRODITE_ADAPTER_AUTH_TOKEN" in text
