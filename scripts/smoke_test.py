"""Nebius Token Factory 연결 검증: NVIDIA 텍스트 모델 + 비전 모델."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nebius_client import NebiusClient

c = NebiusClient()

NVIDIA = [
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/Nemotron-3_5-Lightning",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
]
VISION = ["openbmb/MiniCPM-V-4_5", "google/gemma-3-27b-it"]

print("=" * 62)
print("1) NVIDIA text models")
print("=" * 62)
for m in NVIDIA:
    t = time.time()
    try:
        out = c.chat("Answer in one short sentence: what is a safety hazard?",
                     model=m, max_tokens=60)
        print(f"[OK  {time.time()-t:5.1f}s] {m}\n     {out[:120]}")
    except Exception as e:
        print(f"[FAIL] {m} -> {type(e).__name__}: {str(e).splitlines()[0][:120]}")

print()
print("=" * 62)
print("2) Vision models (image input)")
print("=" * 62)
img = sys.argv[1] if len(sys.argv) > 1 else None
if not img:
    print("   (이미지 경로 미지정 - 건너뜀)")
else:
    for m in VISION:
        t = time.time()
        try:
            out = c.chat_with_images(
                "Describe this image in one sentence.", [img],
                model=m, max_tokens=100)
            print(f"[OK  {time.time()-t:5.1f}s] {m}\n     {out[:160]}")
        except Exception as e:
            print(f"[FAIL] {m} -> {type(e).__name__}: {str(e).splitlines()[0][:120]}")
