"""사용 가능한 모델 목록 확인 (특히 NVIDIA 모델의 정확한 ID)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nebius_client import get_client

client = get_client()
models = client.list_models()

print(f"총 {len(models)}개 모델\n")

nvidia = [m for m in models if "nvidia" in m.lower() or "cosmos" in m.lower() or "nemotron" in m.lower()]
print("=== NVIDIA / Cosmos / Nemotron ===")
for m in nvidia:
    print("  ", m)
if not nvidia:
    print("   (없음)")

print("\n=== 전체 ===")
for m in models:
    print("  ", m)
