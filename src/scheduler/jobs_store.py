"""
스케줄 작업 정의 저장소

JSON 파일 (config/scheduled_jobs.json)로 작업 목록을 관리.
작업은 다음 종류 중 하나:
  - "blogdex_pipeline" : 특정 캠페인의 블덱스 시트 파이프라인 실행
  - "naver_check"      : 검수 일괄 실행 (CSV 경로 필요)
  - "custom_command"   : 임의의 셸 명령 (전체 명령어를 사용자가 입력)

스케줄 형식 (단순 cron 부분집합):
  - "daily"  : 매일 HH:MM
  - "weekly" : 매주 요일 HH:MM (요일은 mon/tue/wed/thu/fri/sat/sun)
  - "hourly" : 매시 정각 (또는 분 지정)
  - "every"  : N분마다 / N시간마다

각 작업은:
  {
    "id": "uuid",
    "name": "사용자가 보는 이름",
    "type": "blogdex_pipeline",
    "params": {...},
    "schedule": {"kind": "daily", "time": "09:00"},
    "enabled": true,
    "last_run": "2026-05-06T09:00:00",
    "last_status": "success" | "failed" | null,
    "created_at": "..."
  }
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_PATH = PROJECT_ROOT / "config" / "scheduled_jobs.json"


# =============================================================================
# 데이터 구조
# =============================================================================

JOB_TYPES = {
    "blogdex_pipeline": "블덱스 시트 자동 분류",
    "naver_check": "네이버 노출 일괄 검수",
    "custom_command": "사용자 지정 명령어",
}

SCHEDULE_KINDS = {
    "daily": "매일 (시:분)",
    "weekly": "매주 요일 (요일+시:분)",
    "hourly": "매시 (분)",
    "every": "N분/N시간마다",
}

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# =============================================================================
# 로드/저장
# =============================================================================

def _read_raw() -> list[dict]:
    if not JOBS_PATH.exists():
        return []
    try:
        with open(JOBS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _write_raw(jobs: list[dict]):
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def list_jobs() -> list[dict]:
    """등록된 모든 스케줄 작업."""
    return _read_raw()


def get_job(job_id: str) -> Optional[dict]:
    for j in _read_raw():
        if j.get("id") == job_id:
            return j
    return None


def add_job(
    name: str,
    job_type: str,
    params: dict,
    schedule: dict,
    enabled: bool = True,
) -> str:
    """새 작업 추가. 반환: 새 job_id"""
    if job_type not in JOB_TYPES:
        raise ValueError(f"알 수 없는 작업 종류: {job_type}")
    if schedule.get("kind") not in SCHEDULE_KINDS:
        raise ValueError(f"알 수 없는 스케줄 종류: {schedule.get('kind')}")

    new_id = uuid.uuid4().hex[:8]
    job = {
        "id": new_id,
        "name": name,
        "type": job_type,
        "params": params,
        "schedule": schedule,
        "enabled": enabled,
        "last_run": None,
        "last_status": None,
        "created_at": datetime.now().isoformat(),
    }
    jobs = _read_raw()
    jobs.append(job)
    _write_raw(jobs)
    return new_id


def update_job(job_id: str, **changes) -> bool:
    jobs = _read_raw()
    for i, j in enumerate(jobs):
        if j.get("id") == job_id:
            jobs[i] = {**j, **changes}
            _write_raw(jobs)
            return True
    return False


def delete_job(job_id: str) -> bool:
    jobs = _read_raw()
    new = [j for j in jobs if j.get("id") != job_id]
    if len(new) == len(jobs):
        return False
    _write_raw(new)
    return True


def mark_run(job_id: str, status: str):
    update_job(
        job_id,
        last_run=datetime.now().isoformat(),
        last_status=status,
    )
