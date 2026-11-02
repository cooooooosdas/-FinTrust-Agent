# -*- coding: utf-8 -*-
"""打包并审计金枢 FinTrust Agent 竞赛源码交付包。"""
from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path

# 仓库根目录 = 本脚本（submission/tools/）的上两级，不依赖任何机器绝对路径
ROOT = Path(__file__).resolve().parents[2]
_zip_out = os.environ.get("FINTRUST_ZIP_OUT")
OUT = Path(_zip_out) if _zip_out else ROOT / "submission" / "03_金枢完整源代码.zip"
TOP = "jingshu"
BUILD = ROOT / "submission" / "tools"
OUT.parent.mkdir(parents=True, exist_ok=True)
BUILD.mkdir(parents=True, exist_ok=True)

EXCLUDED_PARTS = {
    ".git", ".workbuddy", ".venv", "node_modules", "__pycache__", ".pytest_cache",
    ".idea", ".vscode", ".screenshots", "dist", "build", "coverage", "htmlcov",
}
EXCLUDED_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm",
    ".pyc", ".pyo", ".log", ".tmp", ".bak", ".swp", ".coverage", ".tsbuildinfo",
}
EXCLUDED_NAMES = {".env", ".env.local", ".env.development", ".env.production", ".coverage"}
REQUIRED = [
    "jingshu/README.md",
    "jingshu/LICENSE",
    "jingshu/.gitignore",
    "jingshu/start_backend.bat",
    "jingshu/start_frontend.bat",
    "jingshu/backend/requirements.txt",
    "jingshu/backend/pytest.ini",
    "jingshu/backend/run.py",
    "jingshu/backend/.env.example",
    "jingshu/backend/app/main.py",
    "jingshu/backend/tests/test_policy.py",
    "jingshu/backend/scripts/init_db.py",
    "jingshu/backend/scripts/migrate_v030.py",
    "jingshu/backend/scripts/migrate_v040.py",
    "jingshu/backend/scripts/prepare_demo.py",
    "jingshu/backend/scripts/verify_audit_integrity.py",
    "jingshu/backend/scripts/smoke_api.py",
    "jingshu/frontend/package.json",
    "jingshu/frontend/package-lock.json",
    "jingshu/frontend/.env.example",
    "jingshu/frontend/index.html",
    "jingshu/frontend/vite.config.ts",
    "jingshu/frontend/src/App.tsx",
    "jingshu/docs/API.md",
    "jingshu/docs/ARCHITECTURE.md",
    "jingshu/docs/SECURITY.md",
    "jingshu/docs/DEPLOYMENT.md",
    "jingshu/docs/PPT_OUTLINE_10MIN.md",
    "jingshu/docs/FINAL_KNOWN_LIMITATIONS.md",
    "jingshu/submission/tools/build_pdfs.py",
    "jingshu/submission/tools/build_pptx.js",
    "jingshu/submission/tools/package_source.py",
    "jingshu/submission/tools/README.md",
]
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt", ".ini", ".example", ".bat", ".css", ".html", ".toml", ".yml", ".yaml"}


def should_include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if rel.parts[:2] == ("backend", "data"):
        return False
    if parts & EXCLUDED_PARTS:
        return False
    if path.name in EXCLUDED_NAMES:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if any(path.name.endswith(s) for s in (".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm")):
        return False
    if path.is_file() and not path.is_symlink():
        return True
    return False


def collect_candidates():
    candidates: list[Path] = []
    # 明确纳入独立部署所需的根文件和后端/前端源码。
    for rel in ["README.md", "LICENSE", ".gitignore", "start_backend.bat", "start_frontend.bat"]:
        p = ROOT / rel
        if p.exists():
            candidates.append(p)
    for base in ["backend", "frontend", "docs", "submission/tools"]:
        for p in (ROOT / base).rglob("*"):
            if p.is_file() and should_include(p):
                candidates.append(p)
    return sorted(set(candidates), key=lambda p: str(p.relative_to(ROOT)).lower())


def scan_text(name: str, data: bytes):
    ext = Path(name).suffix.lower()
    if ext not in TEXT_EXT and not name.endswith(".env.example"):
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    hits = []
    patterns = [
        ("openai_secret", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
        ("generic_api_key_assignment", re.compile(r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9_\-+/=.]{24,}['\"]")),
        ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9_\-.]{24,}")),
    ]
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.strip().startswith(("#", "//")):
            continue
        for label, pat in patterns:
            if pat.search(line):
                # 演示密码与空配置不报；默认开发密钥由 separate note 说明。
                if "Demo1234" in line or '""' in line or "=" in line and line.rstrip().endswith("="):
                    continue
                hits.append({"file": name, "line": i, "type": label, "text": line.strip()[:180]})
    return hits


def main():
    candidates = collect_candidates()
    if OUT.exists():
        OUT.unlink()
    included, hits = [], []
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in candidates:
            rel = p.relative_to(ROOT).as_posix()
            arcname = f"{TOP}/{rel}"
            data = p.read_bytes()
            zf.writestr(arcname, data)
            included.append(arcname)
            hits.extend(scan_text(arcname, data))
    with zipfile.ZipFile(OUT, "r") as zf:
        bad = zf.testzip()
        names = zf.namelist()
    missing = [r for r in REQUIRED if r not in names]
    forbidden_hits = [n for n in names if any(part in n.split("/") for part in EXCLUDED_PARTS) or n.endswith(tuple(EXCLUDED_SUFFIXES))]
    report = {
        "archive": str(OUT),
        "size_bytes": OUT.stat().st_size,
        "file_count": len(names),
        "directory_count": len({str(Path(n).parent).replace("\\", "/") for n in names if "/" in n.strip("/")}),
        "zip_test": "PASS" if bad is None else f"FAIL:{bad}",
        "required_missing": missing,
        "forbidden_entries": forbidden_hits,
        "suspicious_findings": hits,
        "development_default_secret_note": "源码中 MFA/Session/Audit 密钥存在本地演示默认值；ZIP 不包含真实 .env 或已配置密钥，部署时必须通过环境变量覆盖。",
        "files": names,
    }
    (BUILD / "zip_validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "files"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
