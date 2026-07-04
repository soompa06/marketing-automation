"""
판매자용 키페어 생성기 (1회 실행).

Ed25519 키페어를 만들어:
  - 개인키(private) → 판매자만 보관. 이 키로 고객 라이선스에 '서명'한다.
                      절대 배포본/깃에 포함하지 말 것.
  - 공개키(public)  → 앱에 내장(src/licensing/pubkey.pem). 라이선스 '검증'에 사용.

사용:
    python src/licensing/keygen.py
    # 또는 저장 위치 지정
    python src/licensing/keygen.py --out ~/.soom_marketing_keys
"""
from __future__ import annotations

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLED_PUBKEY = Path(__file__).resolve().parent / "pubkey.pem"
DEFAULT_KEY_DIR = Path.home() / ".soom_marketing_keys"


def generate(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_path = out_dir / "private_key.pem"
    pub_path = out_dir / "public_key.pem"
    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)
    try:
        priv_path.chmod(0o600)
    except Exception:
        pass

    # 앱에 내장될 공개키도 함께 복사
    BUNDLED_PUBKEY.write_bytes(pub_pem)

    return priv_path, pub_path


def main():
    parser = argparse.ArgumentParser(description="판매자 라이선스 키페어 생성 (1회)")
    parser.add_argument("--out", default=str(DEFAULT_KEY_DIR),
                        help=f"키 저장 폴더 (기본: {DEFAULT_KEY_DIR})")
    args = parser.parse_args()
    out_dir = Path(args.out).expanduser()

    if (out_dir / "private_key.pem").exists():
        print(f"⚠️ 이미 키가 있습니다: {out_dir/'private_key.pem'}")
        print("   덮어쓰면 기존에 발급한 모든 라이선스가 무효가 됩니다.")
        if input("   정말 새로 생성할까요? (yes 입력): ").strip().lower() != "yes":
            print("취소했습니다.")
            return

    priv_path, pub_path = generate(out_dir)
    print("✅ 키페어 생성 완료")
    print(f"   🔒 개인키(판매자 비밀, 백업 필수): {priv_path}")
    print(f"   🌐 공개키: {pub_path}")
    print(f"   📦 앱 내장 공개키 갱신됨: {BUNDLED_PUBKEY}")
    print()
    print("⚠️ 개인키는 절대 공유/배포/깃 커밋하지 마세요. 분실 시 라이선스 발급 불가.")


if __name__ == "__main__":
    main()
