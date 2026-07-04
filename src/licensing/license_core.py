"""
라이선스 발급(서명) + 검증 + 기간/기능 제어 — 오프라인 Ed25519 방식.

[발급] 판매자가 개인키로 라이선스 페이로드에 서명 → 라이선스 키 문자열 생성.
[검증] 앱(고객 PC)이 내장 공개키로 서명을 확인 + 만료일 + 시계 역행 체크.

라이선스 키 형식:  MKT1.<payload_b64url>.<sig_b64url>
  payload = canonical JSON:
    {
      "lid": 라이선스ID,
      "cust": 고객명/이메일,
      "plan": "basic|pro|all",
      "feat": [추가 기능...]  # plan 외 개별 추가(선택)
      "iss":  발급일 (YYYY-MM-DD),
      "exp":  만료일 (YYYY-MM-DD),  // 없으면 무기한
      "ver":  1
    }

보안 한계(정직하게):
- Python 앱은 디컴파일이 가능해 '완벽한' 복제 방지는 불가능합니다.
- Ed25519 서명은 '개인키 없이 유효한 라이선스 위조'를 막아줍니다(강력).
- 결정적 공격자(바이너리 패치)까지 막진 못하나, 일반 사용자 수준 보호엔 충분합니다.
- 시계 역행(날짜 되돌리기)은 '마지막 실행시각 기록'으로 일부 탐지합니다.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

try:
    from plans import features_for_plan, FEATURES  # 같은 폴더 실행 시
except Exception:  # 패키지/외부 호출
    from licensing.plans import features_for_plan, FEATURES  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLED_PUBKEY = Path(__file__).resolve().parent / "pubkey.pem"
LICENSE_PATH = PROJECT_ROOT / "config" / "license.key"
# 시계 역행 탐지용 (난독화된 마지막 실행시각)
_STATE_PATH = PROJECT_ROOT / "config" / ".license_state"

PREFIX = "MKT1"


# =============================================================================
# 인코딩 헬퍼
# =============================================================================

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _canonical(payload: dict) -> bytes:
    """서명 대상 — 키 정렬 + 공백 없는 JSON (발급/검증 동일해야 함)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


# =============================================================================
# 발급 (판매자: 개인키 필요)
# =============================================================================

def issue_license(private_key_pem: bytes, *, customer: str, plan: str,
                  expires: Optional[str], license_id: str,
                  extra_features: Optional[list[str]] = None,
                  issued: Optional[str] = None) -> str:
    """
    서명된 라이선스 키 문자열 생성.

    Args:
        private_key_pem: 판매자 개인키 PEM bytes
        customer: 고객 식별(이름/이메일)
        plan: basic|pro|all
        expires: 'YYYY-MM-DD' 또는 None(무기한)
        license_id: 고유 ID
        extra_features: 플랜 외 추가 기능 키 목록
    """
    priv = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise ValueError("Ed25519 개인키가 아닙니다.")

    payload = {
        "ver": 1,
        "lid": license_id,
        "cust": customer,
        "plan": (plan or "").lower(),
        "feat": sorted(set(extra_features or [])),
        "iss": issued or date.today().isoformat(),
        "exp": expires or "",
    }
    msg = _canonical(payload)
    sig = priv.sign(msg)
    return f"{PREFIX}.{_b64e(msg)}.{_b64e(sig)}"


# =============================================================================
# 검증 (앱: 공개키 내장)
# =============================================================================

def _load_public_key() -> Optional[Ed25519PublicKey]:
    if not BUNDLED_PUBKEY.exists():
        return None
    try:
        pub = serialization.load_pem_public_key(BUNDLED_PUBKEY.read_bytes())
        return pub if isinstance(pub, Ed25519PublicKey) else None
    except Exception:
        return None


def parse_and_verify(license_str: str) -> dict:
    """
    라이선스 문자열을 검증해 상태 dict 반환.

    Returns:
        {
          "valid": bool,          # 서명+만료+시계 모두 통과
          "reason": str,          # 무효 사유 (valid=False일 때)
          "payload": dict|None,   # 검증된 페이로드
          "expired": bool,
          "days_left": int|None,
          "features": [str],      # 사용 가능 기능
          "plan": str,
        }
    """
    res = {"valid": False, "reason": "", "payload": None, "expired": False,
           "days_left": None, "features": [], "plan": ""}

    s = (license_str or "").strip()
    if not s:
        res["reason"] = "라이선스 키가 비어 있습니다."
        return res

    parts = s.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        res["reason"] = "라이선스 형식이 올바르지 않습니다."
        return res

    pub = _load_public_key()
    if pub is None:
        res["reason"] = "앱에 공개키가 없습니다(빌드 설정 오류)."
        return res

    try:
        msg = _b64d(parts[1])
        sig = _b64d(parts[2])
    except Exception:
        res["reason"] = "라이선스 인코딩 오류."
        return res

    try:
        pub.verify(sig, msg)
    except InvalidSignature:
        res["reason"] = "서명이 유효하지 않습니다(위조되었거나 다른 키로 발급됨)."
        return res
    except Exception as e:
        res["reason"] = f"검증 오류: {e}"
        return res

    try:
        payload = json.loads(msg.decode("utf-8"))
    except Exception:
        res["reason"] = "라이선스 내용을 읽을 수 없습니다."
        return res

    res["payload"] = payload
    res["plan"] = payload.get("plan", "")
    feats = set(features_for_plan(payload.get("plan", "")))
    feats.update(payload.get("feat", []) or [])
    res["features"] = sorted(feats)

    # 만료 + 시계 역행
    today = _trusted_today()
    exp = payload.get("exp", "")
    if exp:
        try:
            exp_d = date.fromisoformat(exp)
        except Exception:
            res["reason"] = "만료일 형식 오류."
            return res
        delta = (exp_d - today).days
        res["days_left"] = delta
        if delta < 0:
            res["expired"] = True
            res["reason"] = f"라이선스가 만료되었습니다 (만료일 {exp})."
            return res

    res["valid"] = True
    return res


# =============================================================================
# 시계 역행 탐지
# =============================================================================

def _trusted_today() -> date:
    """
    시스템 날짜를 쓰되, 과거 실행 기록보다 '뒤로 간' 경우 마지막 본 날짜를 사용.
    (날짜 되돌려 만료를 회피하는 단순 조작 방어 — 완벽하진 않음)
    """
    now = date.today()
    last = _read_last_seen()
    effective = now
    if last and now < last:
        # 시계가 과거로 돌아감 → 마지막으로 본 날짜를 신뢰
        effective = last
    # 더 미래면 기록 갱신
    if not last or now > last:
        _write_last_seen(now)
    return effective


def _read_last_seen() -> Optional[date]:
    try:
        raw = _STATE_PATH.read_text(encoding="utf-8").strip()
        # 가벼운 난독화: base64
        iso = base64.b64decode(raw.encode("ascii")).decode("utf-8")
        return date.fromisoformat(iso)
    except Exception:
        return None


def _write_last_seen(d: date) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        enc = base64.b64encode(d.isoformat().encode("utf-8")).decode("ascii")
        _STATE_PATH.write_text(enc, encoding="utf-8")
    except Exception:
        pass


# =============================================================================
# 고객 PC의 활성 라이선스
# =============================================================================

def load_active() -> dict:
    """config/license.key 를 읽어 검증 결과 반환. 없으면 valid=False."""
    if not LICENSE_PATH.exists():
        return {"valid": False, "reason": "라이선스가 등록되지 않았습니다.",
                "payload": None, "expired": False, "days_left": None,
                "features": [], "plan": ""}
    return parse_and_verify(LICENSE_PATH.read_text(encoding="utf-8"))


def save_active(license_str: str) -> dict:
    """라이선스 키를 검증 후 저장. 결과 반환(무효면 저장 안 함)."""
    res = parse_and_verify(license_str)
    if res["valid"]:
        LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        LICENSE_PATH.write_text(license_str.strip(), encoding="utf-8")
    return res


def remove_active() -> None:
    try:
        if LICENSE_PATH.exists():
            LICENSE_PATH.unlink()
    except Exception:
        pass
