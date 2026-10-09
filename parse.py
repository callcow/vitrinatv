import re
import json
import requests
from pathlib import Path

CONFIG_URL = "https://static-api.mediavitrina.ru/v1/vitrinatv_app/web/3/config.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    "Origin": "https://player.mediavitrina.ru",
    "Referer": "https://player.mediavitrina.ru/",
    "Accept": "*/*",
}

session = requests.Session()


def get_hls(player_url: str) -> tuple[str | None, str]:
    try:
        r = session.get(player_url, headers=HEADERS, timeout=20)
    except Exception as e:
        return None, f"player request failed: {e}"
    if r.status_code != 200:
        return None, f"player status {r.status_code}"

    m = re.search(r'streams_api_v2_url\s*[:=]\s*["\']([^"\']+)["\']', r.text)
    if not m:
        return None, "streams_api_v2_url not found"

    url = (m.group(1).replace("\\/", "/")
           .replace("{{APPLICATION_ID}}", "")
           .replace("{{PLAYER_REFERER_HOSTNAME}}", "vitrina.tv")
           .replace("{{CONFIG_CHECKSUM_SHA256}}", "undefined"))

    try:
        r = session.get(url, headers=HEADERS, timeout=20)
    except Exception as e:
        return None, f"streams request failed: {e}"
    if r.status_code != 200:
        return None, f"streams status {r.status_code}"

    try:
        data = r.json()
    except Exception as e:
        return None, f"json parse failed: {e}"

    hls = data.get("hls")
    if not hls:
        return None, f"no 'hls' key (keys: {list(data.keys())})"

    first = hls[0]
    hls_url = first["url"] if isinstance(first, dict) else first
    if not hls_url:
        return None, "hls[0] empty"

    return hls_url, "ok"


HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Витрина ТВ</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
<style>
  :root {
    --bg: #0f1115;
    --card: #1a1d24;
    --card-hover: #232732;
    --accent: #3ea6ff;
    --text: #eaeef5;
    --muted: #8b93a7;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font: 14px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 16px; }

  header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
  header h1 { font-size: 18px; margin: 0; }
  header .status { color: var(--muted); font-size: 12px; }

  .player {
    position: relative; aspect-ratio: 16/9; background: #000;
    border-radius: 12px; overflow: hidden;
  }
  .player video { width: 100%; height: 100%; display: block; background: #000; }
  .player .now {
    position: absolute; left: 12px; bottom: 12px;
    background: rgba(0,0,0,.6); backdrop-filter: blur(6px);
    padding: 6px 10px; border-radius: 999px; font-size: 13px;
    pointer-events: none;
  }
  .player .spinner {
    position: absolute; inset: 0; display: none;
    align-items: center; justify-content: center;
    color: var(--muted); font-size: 13px;
  }
  .player.loading .spinner { display: flex; }

  .carousel {
    margin-top: 16px;
    display: flex; gap: 10px; overflow-x: auto;
    padding: 6px 2px 14px;
    scroll-snap-type: x mandatory;
    scrollbar-width: thin;
    scrollbar-color: #2a2e3a transparent;
  }
  .carousel::-webkit-scrollbar { height: 8px; }
  .carousel::-webkit-scrollbar-thumb { background: #2a2e3a; border-radius: 8px; }

  .channel {
    flex: 0 0 auto;
    width: 120px;
    background: var(--card);
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 10px 8px;
    cursor: pointer;
    text-align: center;
    scroll-snap-align: start;
    transition: background .15s, border-color .15s;
    user-select: none;
  }
  .channel:hover { background: var(--card-hover); }
  .channel.active { border-color: var(--accent); }
  .channel img {
    width: 100%; height: 60px; object-fit: contain;
    margin-bottom: 6px; pointer-events: none;
  }
  .channel .name {
    font-size: 12px; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  .scroll-hint { color: var(--muted); font-size: 12px; margin-top: -6px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Витрина ТВ</h1>
    <span class="status" id="status">загрузка…</span>
  </header>

  <div class="player" id="player">
    <video id="video" playsinline autoplay muted controls></video>
    <div class="now" id="now">—</div>
    <div class="spinner">подключение…</div>
  </div>

  <div class="scroll-hint">← листайте каналы →</div>
  <div class="carousel" id="carousel"></div>
</div>

<script>
const CHANNELS = __CHANNELS_JSON__;

const video = document.getElementById('video');
const carousel = document.getElementById('carousel');
const nowEl = document.getElementById('now');
const statusEl = document.getElementById('status');
const playerEl = document.getElementById('player');

let hls = null;
let currentSlug = null;

function renderCarousel() {
  carousel.innerHTML = '';
  for (const ch of CHANNELS) {
    const el = document.createElement('div');
    el.className = 'channel';
    el.dataset.slug = ch.slug;
    el.title = ch.title;
    el.innerHTML = `
      ${ch.logo ? `<img src="${ch.logo}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : ''}
      <div class="name">${escapeHtml(ch.title)}</div>
    `;
    el.addEventListener('click', () => play(ch.slug));
    carousel.appendChild(el);
  }
}

function play(slug) {
  const ch = CHANNELS.find(c => c.slug === slug);
  if (!ch) return;
  currentSlug = slug;
  nowEl.textContent = ch.title;
  highlight(slug);
  playerEl.classList.add('loading');

  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute('src');
  video.load();

  if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = ch.hls;
    video.play().catch(() => {});
    video.addEventListener('loadedmetadata', () => playerEl.classList.remove('loading'), { once: true });
  } else if (window.Hls && Hls.isSupported()) {
    hls = new Hls({ lowLatencyMode: true, enableWorker: true });
    hls.loadSource(ch.hls);
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      playerEl.classList.remove('loading');
      video.play().catch(() => {});
    });
    hls.on(Hls.Events.ERROR, (_, data) => {
      if (data.fatal) {
        console.warn('HLS error', data);
        playerEl.classList.remove('loading');
      }
    });
  } else {
    statusEl.textContent = 'HLS не поддерживается этим браузером';
  }
}

function highlight(slug) {
  for (const el of carousel.children) {
    el.classList.toggle('active', el.dataset.slug === slug);
  }
  const active = carousel.querySelector('.channel.active');
  if (active) active.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

statusEl.textContent = `каналов: ${CHANNELS.length}`;
renderCarousel();
if (CHANNELS.length) play(CHANNELS[0].slug);
</script>
</body>
</html>
"""


def build_html(channels: list[dict]) -> str:
    # безопасно встраиваем json в <script>, экранируя </script> и <!--
    payload = json.dumps(channels, ensure_ascii=False)
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")
    return HTML_TEMPLATE.replace("__CHANNELS_JSON__", payload)


def main():
    channels = session.get(CONFIG_URL, headers=HEADERS, timeout=20) \
                      .json()["result"]["channels"]

    total = len(channels)
    ok = 0
    failed = []
    result = []

    for ch in channels:
        slug = ch["channel_slug"]
        title = ch["channel_title"]
        img = (ch.get("channel_img") or {}).get("active") \
              or (ch.get("channel_img") or {}).get("default") or ""

        url, reason = get_hls(ch["web_player_url"])
        if url:
            ok += 1
            result.append({"slug": slug, "title": title, "logo": img, "hls": url})
            print(f"✓ {title}: {url}")
        else:
            failed.append((slug, title, reason))
            print(f"✗ {title}: {reason}")

    print(f"\nСпарсено: {ok} из {total}")
    for slug, title, reason in failed:
        print(f"  - {title} [{slug}]: {reason}")

    Path("channels.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path("index.html").write_text(build_html(result), encoding="utf-8")
    print("\nСохранено: channels.json, index.html")


if __name__ == "__main__":
    main()
