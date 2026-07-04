"""
백그라운드 작업 관리자

문제: Streamlit은 페이지 이동 시 스크립트가 처음부터 다시 실행됨.
     검수 / 보고서 / 블덱스 같은 긴 작업이 페이지 이동으로 중단됨.

해결: subprocess.Popen으로 별도 프로세스 띄우고, 진행 상황을 파일로 추적.
     페이지 이동 후 돌아와도 진행 상황을 다시 읽어와서 표시.

저장 위치: output/.jobs/
- 각 작업은 고유 ID를 가지며 다음 파일들로 추적됨:
  - {job_id}.json — 메타 정보 (시작 시간, 명령어, 종료 코드 등)
  - {job_id}.log  — stdout/stderr 실시간 로그
  - {job_id}.pid  — 프로세스 ID
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils import OUTPUT_DIR, PROJECT_ROOT, get_python_executable

JOBS_DIR = OUTPUT_DIR / ".jobs"


def _ensure_jobs_dir():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def _make_job_id(prefix: str = "job") -> str:
    """타임스탬프 기반 고유 작업 ID."""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


# =============================================================================
# 작업 시작
# =============================================================================

def start_job(
    cmd: list[str],
    job_type: str = "general",
    description: str = "",
) -> str:
    """
    새 백그라운드 작업 시작.
    
    Args:
        cmd: 실행할 명령어 리스트 (예: ["python", "src/...", "--input", "..."])
        job_type: 작업 종류 (검수/보고서/블덱스 등 — 페이지에서 자기 작업만 보여줄 때 필터링)
        description: 사람이 읽을 설명
    
    Returns:
        job_id (UUID 같은 식별자)
    """
    _ensure_jobs_dir()
    job_id = _make_job_id(prefix=job_type)
    
    log_path = JOBS_DIR / f"{job_id}.log"
    meta_path = JOBS_DIR / f"{job_id}.json"
    pid_path = JOBS_DIR / f"{job_id}.pid"
    
    # 로그 파일을 stdout/stderr 모두에 연결
    log_file = open(log_path, "w", encoding="utf-8", buffering=1)  # line-buffered
    log_file.write(f"=== 작업 시작: {datetime.now().isoformat()} ===\n")
    log_file.write(f"명령어: {' '.join(cmd)}\n")
    log_file.write("=" * 60 + "\n\n")
    log_file.flush()
    
    # subprocess 시작 — 부모(Streamlit) 죽어도 살아남도록 setsid
    try:
        if hasattr(os, "setsid"):  # macOS/Linux
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=str(PROJECT_ROOT),
                preexec_fn=os.setsid,  # 새 프로세스 그룹 — 독립 실행
            )
        else:  # Windows
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
    except Exception as e:
        log_file.write(f"\n❌ 프로세스 시작 실패: {e}\n")
        log_file.close()
        raise
    
    # PID 저장
    pid_path.write_text(str(process.pid))
    
    # 메타 저장
    meta = {
        "job_id": job_id,
        "job_type": job_type,
        "description": description,
        "cmd": cmd,
        "pid": process.pid,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "exit_code": None,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    
    return job_id


# =============================================================================
# 작업 상태 조회
# =============================================================================

def is_running(pid: int) -> bool:
    """
    PID가 실제로 살아있는지 확인.

    주의: 종료됐지만 부모가 거두지 않은 '좀비(defunct)' 프로세스는
    os.kill(pid, 0)이 성공해버려 살아있는 것으로 오판된다.
    → 우리 자식이면 waitpid로 거두고, 아니면 ps 상태(Z)로 좀비를 걸러낸다.
    """
    if pid <= 0:
        return False

    # 1) 우리(이 프로세스)의 자식이면 좀비를 거둬서 종료 여부를 확정한다.
    try:
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            return False        # 방금 종료됨 → 좀비 수거 완료
        if wpid == 0:
            return True         # 아직 실행 중
    except ChildProcessError:
        pass                    # 우리 자식이 아님 → 아래 단계로
    except OSError:
        pass

    # 2) 존재 여부 확인
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False

    # 3) 존재하지만 좀비(Z) 상태면 실행 중이 아님
    try:
        out = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True, text=True, timeout=2,
        )
        state = (out.stdout or "").strip()
        if state.startswith("Z"):
            return False
    except Exception:
        pass

    return True


def get_job_status(job_id: str) -> dict:
    """
    작업 상태 반환.
    
    Returns:
        {
            "job_id": str,
            "running": bool,
            "started_at": str,
            "finished_at": str or None,
            "exit_code": int or None,
            "description": str,
            ...
        }
    """
    meta_path = JOBS_DIR / f"{job_id}.json"
    if not meta_path.exists():
        return {"job_id": job_id, "running": False, "error": "작업을 찾을 수 없음"}
    
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    
    pid = meta.get("pid", 0)
    running = is_running(pid) if pid > 0 else False
    
    # 더 이상 실행 중이 아닌데 finished_at이 비어있으면 종료 처리
    if not running and meta.get("finished_at") is None:
        meta["finished_at"] = datetime.now().isoformat()
        # exit code는 wait() 호출 안 했으면 알 수 없음 — 로그 마지막 줄로 추측
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    
    meta["running"] = running
    return meta


def read_log(job_id: str, max_lines: int = 200) -> str:
    """작업의 로그 마지막 N줄 읽기."""
    log_path = JOBS_DIR / f"{job_id}.log"
    if not log_path.exists():
        return "(로그 없음)"
    
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").split("\n")
        if len(lines) > max_lines:
            return "... (이전 줄 생략) ...\n" + "\n".join(lines[-max_lines:])
        return "\n".join(lines)
    except Exception as e:
        return f"(로그 읽기 실패: {e})"


def job_outcome(job_id: str) -> dict:
    """
    완료된 작업의 성공/실패를 로그로 판정.
    UI에서 raw 파이썬 traceback 대신 '실패(사유)'로 깔끔히 표기하기 위함.
    Returns: {"ok": bool, "reason": str}
    """
    log = read_log(job_id, max_lines=400)
    crash_markers = [
        "Traceback (most recent call last)", "TargetClosedError",
        "ModuleNotFoundError", "ConnectionError", "APIError",
        "❌ 캠페인", "처리 실패", "EPIPE",
    ]
    hit = next((m for m in crash_markers if m in log), None)
    if hit:
        reason = ""
        for line in log.splitlines():
            if ("Error" in line and ":" in line) or "오류" in line:
                reason = line.strip()[:120]
        return {"ok": False, "reason": reason or hit}
    return {"ok": True, "reason": ""}


def clear_job_logs(job_type: Optional[str] = None, only_failed: bool = False) -> int:
    """
    완료된 작업 로그/메타/pid 삭제. 실행 중인 작업은 보호.
    Returns: 삭제한 작업 수
    """
    _ensure_jobs_dir()
    removed = 0
    for meta_path in list(JOBS_DIR.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job_type is not None and meta.get("job_type") != job_type:
            continue
        pid = meta.get("pid", 0)
        if pid > 0 and is_running(pid):
            continue
        jid = meta.get("job_id")
        if not jid:
            continue
        if only_failed and job_outcome(jid).get("ok"):
            continue
        for ext in (".json", ".log", ".pid"):
            f = JOBS_DIR / f"{jid}{ext}"
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass
        removed += 1
    return removed


# =============================================================================
# 작업 목록
# =============================================================================

def list_jobs(job_type: Optional[str] = None, limit: int = 20) -> list[dict]:
    """
    저장된 작업들 목록 (최신순).
    
    Args:
        job_type: 특정 종류만 필터 (None이면 전체)
        limit: 최대 개수
    """
    _ensure_jobs_dir()
    
    jobs = []
    for meta_path in sorted(JOBS_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if job_type and meta.get("job_type") != job_type:
                continue
            
            # 살아있는지 다시 확인
            pid = meta.get("pid", 0)
            meta["running"] = is_running(pid) if pid > 0 else False
            
            jobs.append(meta)
            if len(jobs) >= limit:
                break
        except Exception:
            continue
    
    return jobs


def get_active_jobs(job_type: Optional[str] = None) -> list[dict]:
    """현재 실행 중인 작업들만."""
    return [j for j in list_jobs(job_type=job_type, limit=50) if j.get("running")]


# =============================================================================
# 작업 중지/정리
# =============================================================================

def stop_job(job_id: str) -> bool:
    """작업 강제 종료."""
    status = get_job_status(job_id)
    if not status.get("running"):
        return False
    
    pid = status.get("pid", 0)
    if pid <= 0:
        return False
    
    try:
        if hasattr(os, "killpg"):  # macOS/Linux
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:  # Windows
            os.kill(pid, signal.SIGTERM)
        
        # 잠시 대기 후 강제 종료
        time.sleep(2)
        if is_running(pid):
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        
        return True
    except Exception:
        return False


def cleanup_finished_jobs(keep_recent: int = 10) -> int:
    """완료된 작업 파일들 정리 (최근 N개만 보존)."""
    _ensure_jobs_dir()
    
    finished = []
    for meta_path in sorted(JOBS_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            pid = meta.get("pid", 0)
            if not is_running(pid):
                finished.append((meta_path, meta["job_id"]))
        except Exception:
            continue
    
    # 최근 N개 외 삭제
    deleted = 0
    for meta_path, job_id in finished[keep_recent:]:
        try:
            meta_path.unlink()
            log_path = JOBS_DIR / f"{job_id}.log"
            pid_path = JOBS_DIR / f"{job_id}.pid"
            if log_path.exists():
                log_path.unlink()
            if pid_path.exists():
                pid_path.unlink()
            deleted += 1
        except Exception:
            continue
    
    return deleted
