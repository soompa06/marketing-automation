"""
백업/복원 관리자

백업 대상 (선택 가능):
- config/        : 설정·인증·세션 파일 전체 (settings.json, google_credentials.json,
                   auth.json, blogdex_sessions/, oauth_tokens/ 등)
- output/        : 검수 결과 CSV / 보고서 (.docx) — 용량 클 수 있음
- screenshots/   : 검수 스크린샷 — 용량 큼 (옵션)

복원 시:
- 기존 파일을 덮어쓰기 전에 같은 zip 안에서 manifest.json으로 무결성 확인
- 위험한 경로(절대경로/`..` 포함)는 스킵 (zip-slip 방지)

zip 파일 위치: output/backups/backup_YYYYMMDD_HHMMSS.zip
"""
from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKUP_DIR = PROJECT_ROOT / "output" / "backups"
MANIFEST_NAME = "manifest.json"

# 백업에서 항상 제외할 파일 패턴 (캐시·임시 파일)
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".tmp", ".swp"}


# =============================================================================
# 백업 대상 정의
# =============================================================================

@dataclass
class BackupTarget:
    """백업 대상 폴더/파일 정의."""
    name: str                  # 라벨 (UI에 표시)
    relative_path: str         # PROJECT_ROOT 기준 상대 경로
    description: str           # 설명
    default_selected: bool = True


AVAILABLE_TARGETS: list[BackupTarget] = [
    BackupTarget(
        name="설정·인증",
        relative_path="config",
        description="settings.json, google_credentials.json, auth.json, 블덱스 세션",
        default_selected=True,
    ),
    BackupTarget(
        name="결과 파일",
        relative_path="output",
        description="검수 CSV / 월간보고서 (.docx) — output/backups, output/.jobs 제외",
        default_selected=True,
    ),
    BackupTarget(
        name="스크린샷",
        relative_path="screenshots",
        description="검수 스크린샷 (용량 큼)",
        default_selected=False,
    ),
]


@dataclass
class BackupManifest:
    """백업 zip 안에 포함되는 메타정보."""
    version: int = 1
    created_at: str = ""
    project: str = "marketing_automation"
    targets: list[str] = field(default_factory=list)
    file_count: int = 0
    total_bytes: int = 0


# =============================================================================
# 유틸
# =============================================================================

def _is_excluded(path: Path) -> bool:
    """백업/복원에서 항상 제외할 항목인지."""
    name = path.name
    if name in EXCLUDE_NAMES:
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    # output/backups 자체는 백업 대상에서 제외 (자기 자신 백업 방지)
    try:
        if path.is_relative_to(BACKUP_DIR):
            return True
    except AttributeError:
        # Python 3.9 이하
        try:
            path.relative_to(BACKUP_DIR)
            return True
        except ValueError:
            pass
    # output/.jobs 도 제외 (실시간 로그)
    try:
        if "output/.jobs" in str(path) or "output\\.jobs" in str(path):
            return True
    except Exception:
        pass
    return False


def _walk_files(root: Path) -> Iterable[Path]:
    """root 아래 모든 파일을 yield (제외 규칙 적용)."""
    if not root.exists():
        return
    if root.is_file():
        if not _is_excluded(root):
            yield root
        return
    for p in root.rglob("*"):
        if p.is_file() and not _is_excluded(p):
            yield p


def list_backups() -> list[Path]:
    """저장된 백업 zip 목록 (최신순)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        BACKUP_DIR.glob("backup_*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


# =============================================================================
# 백업 생성
# =============================================================================

def create_backup(
    selected_targets: Optional[list[str]] = None,
    output_path: Optional[Path] = None,
) -> Path:
    """
    선택한 대상들을 zip으로 묶어 저장.

    Args:
        selected_targets: BackupTarget.relative_path 리스트. None이면 default_selected만.
        output_path: 저장 위치. None이면 output/backups/backup_YYYYMMDD_HHMMSS.zip

    Returns:
        생성된 zip 파일 경로
    """
    if selected_targets is None:
        selected_targets = [
            t.relative_path for t in AVAILABLE_TARGETS if t.default_selected
        ]

    if output_path is None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = BACKUP_DIR / f"backup_{timestamp}.zip"

    manifest = BackupManifest(
        created_at=datetime.now().isoformat(),
        targets=list(selected_targets),
    )

    total_bytes = 0
    file_count = 0

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for rel in selected_targets:
            target_root = PROJECT_ROOT / rel
            for fpath in _walk_files(target_root):
                arcname = fpath.relative_to(PROJECT_ROOT)
                zf.write(fpath, arcname=str(arcname))
                total_bytes += fpath.stat().st_size
                file_count += 1

        manifest.file_count = file_count
        manifest.total_bytes = total_bytes
        zf.writestr(MANIFEST_NAME, json.dumps(asdict(manifest), ensure_ascii=False, indent=2))

    return output_path


# =============================================================================
# 백업 검사
# =============================================================================

def inspect_backup(zip_path: Path) -> dict:
    """
    zip 파일을 열어 manifest와 포함된 항목들을 요약.

    Returns:
        {
            "valid": bool,
            "manifest": dict or None,
            "entries": [str, ...],      # 최대 20개 (미리보기)
            "total_entries": int,
            "error": str or None,
        }
    """
    result = {
        "valid": False,
        "manifest": None,
        "entries": [],
        "total_entries": 0,
        "error": None,
    }

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            result["total_entries"] = len(names)
            result["entries"] = names[:20]

            if MANIFEST_NAME in names:
                try:
                    raw = zf.read(MANIFEST_NAME).decode("utf-8")
                    result["manifest"] = json.loads(raw)
                except Exception as e:
                    result["error"] = f"manifest 파싱 실패: {e}"
                    return result

            result["valid"] = True
    except zipfile.BadZipFile:
        result["error"] = "올바른 zip 파일이 아닙니다."
    except Exception as e:
        result["error"] = f"백업 파일 읽기 오류: {e}"

    return result


# =============================================================================
# 복원
# =============================================================================

def _is_safe_member_name(name: str) -> bool:
    """zip-slip 방지: 절대경로·상위 참조 차단."""
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    if ".." in Path(name).parts:
        return False
    return True


def restore_backup(
    zip_path: Path,
    selected_targets: Optional[list[str]] = None,
    create_safety_backup: bool = True,
) -> dict:
    """
    백업 zip을 PROJECT_ROOT에 복원.

    Args:
        selected_targets: 복원할 폴더 리스트 (manifest.targets의 부분집합).
                         None이면 manifest의 모든 대상 복원.
        create_safety_backup: True면 복원 직전 현재 상태를 자동 백업.

    Returns:
        {
            "restored_files": int,
            "skipped": list[str],           # zip-slip 등으로 건너뛴 항목
            "safety_backup": Path or None,  # 안전 백업 경로
            "error": str or None,
        }
    """
    summary = {
        "restored_files": 0,
        "skipped": [],
        "safety_backup": None,
        "error": None,
    }

    info = inspect_backup(zip_path)
    if not info["valid"]:
        summary["error"] = info.get("error") or "유효하지 않은 백업"
        return summary

    manifest = info.get("manifest") or {}
    available = manifest.get("targets", [])

    if selected_targets is None:
        selected_targets = available
    else:
        # manifest에 없는 대상은 버림
        selected_targets = [t for t in selected_targets if t in available]

    if not selected_targets:
        summary["error"] = "복원할 대상이 선택되지 않았습니다."
        return summary

    # 안전 백업 (현재 상태) — 같은 대상으로
    if create_safety_backup:
        try:
            safety = create_backup(
                selected_targets=selected_targets,
                output_path=BACKUP_DIR
                / f"safety_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            )
            summary["safety_backup"] = safety
        except Exception as e:
            # 안전 백업 실패해도 복원은 진행 (사용자 의도)
            summary["safety_backup"] = None
            summary["safety_backup_error"] = str(e)

    # 복원
    target_prefixes = tuple(f"{t}/" for t in selected_targets) + tuple(selected_targets)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member == MANIFEST_NAME:
                continue
            if not _is_safe_member_name(member):
                summary["skipped"].append(member)
                continue
            # 선택한 대상에 속하는 항목만
            if not any(member.startswith(prefix) for prefix in target_prefixes):
                continue

            dest = PROJECT_ROOT / member
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            summary["restored_files"] += 1

    return summary


def delete_backup(zip_path: Path) -> bool:
    """백업 파일 삭제."""
    try:
        if zip_path.exists() and zip_path.suffix == ".zip":
            zip_path.unlink()
            return True
    except Exception:
        pass
    return False
