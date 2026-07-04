"""
스케줄 데몬

`schedule` 라이브러리로 등록된 작업들을 정해진 시간에 실행.

실행:
  python src/scheduler/runner.py             # 포그라운드
  python src/scheduler/runner.py --once       # 등록된 작업을 한 번만 즉시 실행 (테스트용)
  python src/scheduler/runner.py --run <id>   # 특정 작업 즉시 실행

데몬화는 OS에 맡깁니다 (NAS는 Docker, macOS는 launchd, Linux는 systemd).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import schedule  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHED_LOG_DIR = PROJECT_ROOT / "output" / ".scheduler"

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from scheduler.jobs_store import (  # type: ignore  # noqa: E402
    list_jobs,
    get_job,
    mark_run,
    JOBS_PATH,
)


def _python() -> str:
    """현재 인터프리터 (venv의 python)."""
    return sys.executable


def _ensure_log_dir() -> Path:
    SCHED_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return SCHED_LOG_DIR


# =============================================================================
# 작업 종류별 실행 명령어 빌드
# =============================================================================

def _build_command(job: dict) -> Optional[list[str]]:
    jtype = job.get("type")
    params = job.get("params", {}) or {}

    if jtype == "blogdex_pipeline":
        cmd = [
            _python(),
            str(PROJECT_ROOT / "src" / "blogdex" / "sheet_pipeline.py"),
        ]
        for cname in params.get("campaigns", []):
            cmd += ["--campaign", cname]
        if params.get("dry_run"):
            cmd += ["--dry-run"]
        return cmd

    if jtype == "naver_check":
        input_path = params.get("input_csv")
        if not input_path:
            return None
        cmd = [
            _python(),
            str(PROJECT_ROOT / "src" / "naver_check" / "checker.py"),
            "--batch-input", input_path,
        ]
        return cmd

    if jtype == "custom_command":
        line = params.get("command_line")
        if not line:
            return None
        # 보안: shell=False 유지를 위해 split (간단한 케이스 가정)
        # 사용자가 더 복잡한 명령을 원하면 sh -c로 감쌀 수 있게 옵션 제공
        if params.get("via_shell"):
            return ["/bin/sh", "-c", line]
        import shlex
        return shlex.split(line)

    return None


# =============================================================================
# 실행
# =============================================================================

def run_job_once(job_id: str, log: bool = True) -> dict:
    """
    job_id에 해당하는 작업을 즉시 실행.

    Returns:
        { "ok": bool, "exit_code": int, "log_path": Path or None }
    """
    job = get_job(job_id)
    if not job:
        return {"ok": False, "exit_code": -1, "log_path": None, "error": "작업 없음"}

    cmd = _build_command(job)
    if not cmd:
        return {"ok": False, "exit_code": -1, "log_path": None, "error": "명령어 빌드 실패"}

    log_path: Optional[Path] = None
    log_file = None
    if log:
        _ensure_log_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = SCHED_LOG_DIR / f"{job_id}_{ts}.log"
        log_file = open(log_path, "w", encoding="utf-8", buffering=1)
        log_file.write(f"=== 스케줄 실행: {job.get('name')} ({job_id}) ===\n")
        log_file.write(f"시작: {datetime.now().isoformat()}\n")
        log_file.write(f"명령어: {' '.join(cmd)}\n")
        log_file.write("=" * 60 + "\n")

    try:
        result = subprocess.run(
            cmd,
            stdout=log_file or subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        exit_code = result.returncode
    except Exception as e:
        if log_file:
            log_file.write(f"\n실행 오류: {e}\n")
        exit_code = -1
    finally:
        if log_file:
            log_file.write(f"\n종료: {datetime.now().isoformat()} (exit={exit_code})\n")
            log_file.close()

    status = "success" if exit_code == 0 else "failed"
    mark_run(job_id, status)
    return {"ok": exit_code == 0, "exit_code": exit_code, "log_path": log_path}


# =============================================================================
# 스케줄 등록
# =============================================================================

def _register_to_scheduler(jobs: list[dict]):
    """
    schedule 라이브러리에 작업들 등록.
    매번 새로 만드므로 호출 전에 schedule.clear()를 호출해야 함.
    """
    for job in jobs:
        if not job.get("enabled", True):
            continue
        sch = job.get("schedule", {}) or {}
        kind = sch.get("kind")
        job_id = job["id"]

        try:
            if kind == "daily":
                t = sch.get("time", "09:00")
                schedule.every().day.at(t).do(_run_and_log, job_id)
            elif kind == "weekly":
                day = sch.get("weekday", "mon")
                t = sch.get("time", "09:00")
                getattr(schedule.every(), day).at(t).do(_run_and_log, job_id)
            elif kind == "hourly":
                minute = int(sch.get("minute", 0))
                schedule.every().hour.at(f":{minute:02d}").do(_run_and_log, job_id)
            elif kind == "every":
                n = int(sch.get("n", 1))
                unit = sch.get("unit", "minutes")  # minutes | hours
                if unit == "minutes":
                    schedule.every(n).minutes.do(_run_and_log, job_id)
                elif unit == "hours":
                    schedule.every(n).hours.do(_run_and_log, job_id)
        except Exception as e:
            print(f"[!] 작업 '{job.get('name')}' 등록 실패: {e}")


def _run_and_log(job_id: str):
    print(f"[{datetime.now().isoformat()}] ▶ 작업 실행: {job_id}")
    result = run_job_once(job_id)
    status = "✅ 성공" if result["ok"] else f"❌ 실패 (exit={result['exit_code']})"
    print(f"[{datetime.now().isoformat()}] {status} | 로그: {result.get('log_path')}")


# =============================================================================
# 메인 루프
# =============================================================================

def run_forever(reload_interval_seconds: int = 60):
    """
    데몬 메인 루프. 60초마다 jobs_store를 다시 읽어 신규/변경 사항 반영.
    """
    print(f"[scheduler] 시작 (PID={os.getpid()})")
    print(f"[scheduler] 작업 정의 파일: {JOBS_PATH}")

    last_jobs_mtime = 0.0
    last_check = 0.0

    while True:
        # 정의 파일 변경 감지
        try:
            cur_mtime = JOBS_PATH.stat().st_mtime if JOBS_PATH.exists() else 0
        except Exception:
            cur_mtime = 0

        now = time.time()
        if cur_mtime != last_jobs_mtime or (now - last_check) > reload_interval_seconds:
            jobs = list_jobs()
            schedule.clear()
            _register_to_scheduler(jobs)
            enabled = [j for j in jobs if j.get("enabled", True)]
            print(
                f"[scheduler] 정의 재로드: 총 {len(jobs)}개, 활성 {len(enabled)}개 "
                f"(다음 실행 시각 일부: "
                + ", ".join(
                    str(j.next_run) for j in schedule.get_jobs()[:3]
                )
                + ")"
            )
            last_jobs_mtime = cur_mtime
            last_check = now

        schedule.run_pending()
        time.sleep(5)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="마케팅 자동화 스케줄러")
    parser.add_argument("--once", action="store_true", help="등록된 모든 작업을 즉시 1회 실행")
    parser.add_argument("--run", help="특정 job id를 즉시 실행")
    parser.add_argument("--list", action="store_true", help="등록된 작업 목록만 출력")
    args = parser.parse_args()

    if args.list:
        for j in list_jobs():
            sch = j.get("schedule", {})
            print(
                f"- [{j['id']}] {j['name']} ({j['type']}) | "
                f"{sch.get('kind')} {sch} | "
                f"활성={j.get('enabled', True)} | "
                f"마지막={j.get('last_run')} {j.get('last_status') or ''}"
            )
        return

    if args.run:
        result = run_job_once(args.run)
        print(json.dumps(
            {**result, "log_path": str(result.get("log_path"))},
            ensure_ascii=False,
        ))
        sys.exit(0 if result.get("ok") else 1)

    if args.once:
        for j in list_jobs():
            if not j.get("enabled", True):
                continue
            print(f"\n=== {j['name']} ({j['id']}) ===")
            run_job_once(j["id"])
        return

    run_forever()


if __name__ == "__main__":
    main()
