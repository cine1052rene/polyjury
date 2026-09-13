"""실측: 군청 시간표 이미지 → 비전모델 구조화 추출 정확도."""
import base64, json, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from core.nebius_client import get_client
OUT = Path(__file__).resolve().parents[1] / "scratch" / "ruralbus"
IMGS = {
 "changseon1": "https://www.namhae.go.kr/tour/_res/tour/img/sub/bus_time_img007_202608.jpg",
 "seolcheon": "https://www.namhae.go.kr/tour/_res/tour/img/sub/bus_time_img001_20251222.jpg",
}
PROMPT = ("This is a Korean rural bus timetable image. Transcribe it faithfully into JSON: "
 '{"route":str,"effective_date":str|null,"columns":[stop names in order],'
 '"trips":[{"direction":str,"times":[HH:MM or null per column],"note":str|null}],"footnotes":[str]}. '
 "Copy every trip row. Use null for blank cells. Do not invent. Output JSON only.")
raw = get_client().raw
for name, url in IMGS.items():
    p = OUT / f"{name}.jpg"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    p.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    print(name, p.stat().st_size, "bytes", flush=True)
    data = "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()
    for model in (config.VISION_MODEL, config.VISION_FALLBACK):
        t0 = time.time()
        try:
            r = raw.chat.completions.create(model=model, temperature=0, max_tokens=6000,
                messages=[{"role":"user","content":[{"type":"text","text":PROMPT},{"type":"image_url","image_url":{"url":data}}]}])
            c = r.choices[0].message.content or ""
        except Exception as e:
            c = f"ERROR {e!r}"
        tag = model.split("/")[-1]
        (OUT / f"{name}__{tag}.json").write_text(c, encoding="utf-8")
        print(f"== {name} / {tag} ({round(time.time()-t0,1)}s)\n{c[:1800]}\n", flush=True)
print("DONE")
