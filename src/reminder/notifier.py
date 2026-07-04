"""
크로스 플랫폼 데스크톱 알림.

플랫폼별 전략:
- macOS: osascript (시스템 기본, 추가 패키지 불필요)
- Windows: msg /win32 토스트는 추가 패키지가 필요. plyer가 있으면 시도, 없으면 콘솔 출력.
- Linux: notify-send (있으면), 없으면 콘솔 출력.

알림은 어디까지나 보조 신호 — 실패해도 흐름은 막지 않습니다.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess


def _esc_apple(s: str) -> str:
    """AppleScript용 따옴표/줄바꿈 이스케이프."""
    return (
        (s or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def notify(title: str, message: str, sound: bool = True) -> bool:
    """
    데스크톱 알림 발생.

    Args:
        title: 알림 제목
        message: 알림 본문
        sound: macOS에서 알림음 재생 여부

    Returns:
        성공 여부 (실패해도 예외 안 던짐)
    """
    sys_name = platform.system()
    try:
        if sys_name == "Darwin":
            # AppleScript display notification
            sound_clause = ' sound name "Glass"' if sound else ""
            script = f'display notification "{_esc_apple(message)}" with title "{_esc_apple(title)}"{sound_clause}'
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                timeout=10,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        elif sys_name == "Linux":
            # notify-send 사용 (libnotify-bin 패키지 필요할 수 있음)
            if shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", title, message],
                    check=False,
                    timeout=10,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
        elif sys_name == "Windows":
            # plyer 시도 (선택 패키지)
            try:
                from plyer import notification  # type: ignore
                notification.notify(title=title, message=message, timeout=5)
                return True
            except Exception:
                pass
    except Exception:
        pass

    # 폴백: 콘솔 출력
    print(f"\n🔔 [{title}] {message}\n")
    return False


def copy_to_clipboard(text: str) -> bool:
    """OS 클립보드에 텍스트 복사 (가능한 경우)."""
    sys_name = platform.system()
    try:
        if sys_name == "Darwin":
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"))
            return proc.returncode == 0
        elif sys_name == "Linux":
            if shutil.which("xclip"):
                proc = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                )
                proc.communicate(input=text.encode("utf-8"))
                return proc.returncode == 0
            if shutil.which("wl-copy"):
                proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"))
                return proc.returncode == 0
        elif sys_name == "Windows":
            proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            proc.communicate(input=text.encode("utf-16le"))
            return proc.returncode == 0
    except Exception:
        return False
    return False


if __name__ == "__main__":
    notify("테스트 알림", "리마인더 알림이 정상 동작합니다.")
