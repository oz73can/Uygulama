import os, uuid, threading, subprocess
from flask_cors import CORS
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp

app = Flask(__name__)
CORS(app)
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "outputs")
os.makedirs(OUT, exist_ok=True)
JOBS = {}


def pick_segments(info, count, length):
    dur = info.get("duration") or 0
    length = min(length, max(dur, 5))
    heat = info.get("heatmap")  # YouTube "En çok izlenen kısımlar"
    cands = []
    if heat:
        for h in sorted(heat, key=lambda x: -x["value"]):
            mid = (h["start_time"] + h["end_time"]) / 2
            cands.append((mid, h["value"]))
    else:  # heatmap yoksa videoya eşit dağıt
        step = dur / (count + 1)
        cands = [(step * (i + 1), 0.5) for i in range(count)]
    chosen = []
    for mid, val in cands:
        start = max(0, min(mid - length / 2, dur - length))
        if all(abs(start - s) >= length for s, _ in chosen):
            chosen.append((start, val))
        if len(chosen) == count:
            break
    return sorted(chosen), length


def run(job_id, url, count, length):
    job = JOBS[job_id]
    try:
        job.update(status="İndiriliyor…", progress=5)
        d = os.path.join(OUT, job_id)
        os.makedirs(d)
        opts = {"format": "bv*[height<=720]+ba/b[height<=720]/b",
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(d, "source.%(ext)s"), "quiet": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
        src = os.path.join(d, "source.mp4")
        job.update(title=info.get("title", ""), status="Anlar seçiliyor…", progress=40)
        segs, length = pick_segments(info, count, length)
        flt = ("[0:v]split[a][b];[a]scale=720:1280:force_original_aspect_ratio=increase,"
               "crop=720:1280,boxblur=15:3[bg];[b]scale=720:-2[fg];"
               "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p")
        for i, (start, val) in enumerate(segs, 1):
            job.update(status=f"Short {i}/{len(segs)} hazırlanıyor…",
                       progress=40 + int(55 * (i - 1) / len(segs)))
            name = f"short_{i}.mp4"
            p = subprocess.run(["ffmpeg", "-y", "-ss", str(start), "-t", str(length), "-i", src,
                            "-filter_complex", flt, "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "24", "-threads", "1", "-c:a", "aac", "-movflags", "+faststart",
                            os.path.join(d, name)], capture_output=True, text=True)
            if p.returncode:
                raise RuntimeError("ffmpeg: " + p.stderr[-200:])
            job["clips"].append({"file": f"/files/{job_id}/{name}", "name": name,
                                 "start": int(start), "score": round(val * 100)})
        os.remove(src)
        job.update(status="Hazır!", progress=100, done=True)
    except Exception as e:
        job.update(status="Hata: " + str(e)[:200], error=True, done=True)


@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.post("/api/process")
def process():
    b = request.get_json()
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {"status": "Başlıyor…", "progress": 0, "clips": [], "done": False}
    threading.Thread(target=run, args=(jid, b["url"], int(b.get("count", 3)),
                                       int(b.get("length", 30))), daemon=True).start()
    return jsonify(id=jid)


@app.get("/api/status/<jid>")
def status(jid):
    return jsonify(JOBS.get(jid, {"error": True, "status": "Bulunamadı", "done": True}))


@app.get("/files/<jid>/<name>")
def files(jid, name):
    return send_from_directory(os.path.join(OUT, jid), name,
                               as_attachment=request.args.get("dl") == "1")


PWA = {"manifest.json", "icon-192.png", "icon-512.png", "apple-touch-icon.png"}


@app.get("/<name>")
def pwa(name):
    if name not in PWA:
        return "", 404
    return send_from_directory(BASE, name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
