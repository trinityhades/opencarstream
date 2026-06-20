import json
import os
from urllib.parse import quote

from .config import *
from .media import _ffmpeg_hwaccel_args, _select_h264_encoder
from .state import registry

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCarStream — Login</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Rajdhani:wght@500;700&display=swap');
  :root {
    --red: #e31937;
    --red-glow: rgba(227, 25, 55, 0.4);
    --dark: #090909;
    --panel: rgba(17, 17, 23, 0.75);
    --border: rgba(37, 37, 48, 0.8);
    --text: #e0e0ee;
    --muted: #85859e;
    --input-bg: rgba(13, 13, 20, 0.6);
  }
  @media(prefers-color-scheme:light) {
    :root {
      --dark: #f0f0f3;
      --panel: rgba(255, 255, 255, 0.8);
      --border: rgba(216, 216, 224, 0.8);
      --text: #1a1a2e;
      --muted: #78788f;
      --input-bg: rgba(234, 234, 240, 0.6);
    }
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: radial-gradient(circle at center, #1b0e12 0%, var(--dark) 100%);
    color: var(--text);
    font-family: 'Rajdhani', sans-serif;
    font-size: 20px;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
  }
  .login-container {
    width: 100%;
    max-width: 420px;
    background: var(--panel);
    border: 1px solid var(--border);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-radius: 16px;
    padding: 40px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5), 0 0 20px rgba(227, 25, 55, 0.05);
    text-align: center;
    animation: fadeIn 0.6s ease-out;
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
  h1 {
    font-family: 'Orbitron', monospace;
    font-weight: 900;
    font-size: 2.2rem;
    color: var(--red);
    letter-spacing: .12em;
    text-shadow: 0 0 20px var(--red-glow);
    margin-bottom: 6px;
  }
  .sub {
    color: var(--muted);
    font-size: .85rem;
    letter-spacing: .08em;
    text-transform: uppercase;
    margin-bottom: 35px;
  }
  .form-group {
    margin-bottom: 24px;
    text-align: left;
  }
  label {
    display: block;
    font-family: 'Orbitron', monospace;
    font-size: 0.75rem;
    color: var(--muted);
    margin-bottom: 8px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }
  input[type="password"] {
    width: 100%;
    background: var(--input-bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    font-size: 1.1rem;
    outline: none;
    transition: all 0.3s ease;
  }
  input[type="password"]:focus {
    border-color: var(--red);
    box-shadow: 0 0 10px var(--red-glow);
  }
  .error-message {
    background: rgba(227, 25, 55, 0.12);
    color: var(--red);
    border: 1px solid rgba(227, 25, 55, 0.3);
    border-radius: 8px;
    padding: 12px;
    font-size: 0.9rem;
    margin-bottom: 24px;
    text-align: left;
    display: none;
  }
  button {
    width: 100%;
    background: var(--red);
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 14px 20px;
    font-family: 'Orbitron', monospace;
    font-weight: 700;
    font-size: 0.9rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(227, 25, 55, 0.2);
    transition: all 0.2s ease;
  }
  button:hover {
    background: #ff2a4b;
    box-shadow: 0 6px 16px rgba(227, 25, 55, 0.4);
    transform: translateY(-1px);
  }
  button:active {
    transform: translateY(1px);
  }
</style>
</head>
<body>
<div class="login-container">
  <h1>Tesla Player</h1>
  <p class="sub">Streaming launcher for Tesla</p>
  
  <div id="error" class="error-message">{{error_msg}}</div>
  
  <form method="POST" action="/login{{next_query}}">
    <div class="form-group">
      <label for="password">Admin Password</label>
      <input type="password" id="password" name="password" required autofocus placeholder="••••••••">
    </div>
    <button type="submit">Unlock Console</button>
  </form>
</div>

<script>
  // Show error if placeholder is replaced
  const errText = document.getElementById("error").textContent.trim();
  if (errText && errText !== "{{" + "error_msg" + "}}") {
    document.getElementById("error").style.display = "block";
  }
</script>
</body>
</html>
"""


STATUS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCarStream — Streaming for Tesla vehicles</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Rajdhani:wght@300;500&display=swap');
  :root{--red:#e31937;--dark:#090909;--panel:#111117;--border:#252530;--text:#e0e0ee;--muted:#555568;--input-bg:#0d0d14;--thumb-bg:#1a1a24;}
  @media(prefers-color-scheme:light){:root{--dark:#f4f4f6;--panel:#ffffff;--border:#d8d8e0;--text:#1a1a2e;--muted:#888899;--input-bg:#eaeaf0;--thumb-bg:#dcdce8;}}
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:var(--dark);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:21px;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:24px 32px;}
  h1{font-family:'Orbitron',monospace;font-weight:900;font-size:2.4rem;color:var(--red);letter-spacing:.12em;text-shadow:0 0 24px rgba(227,25,55,.45);margin-bottom:6px;}
  .sub{color:var(--muted);font-size:.9rem;letter-spacing:.08em;text-transform:uppercase;margin-bottom:20px;}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;width:100%;max-width:1600px;}
  .tab-btn{font-family:'Orbitron',monospace;font-size:.8rem;letter-spacing:.08em;padding:11px 20px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--muted);cursor:pointer;transition:all .15s;}
  .tab-btn.active{background:var(--red);color:#fff;border-color:var(--red);}
  .tab-panel{display:none;width:100%;max-width:1600px;}
  .tab-panel.active{display:block;}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;width:100%;padding:32px 40px;margin-bottom:24px;}
  .card h2{font-family:'Orbitron',monospace;font-size:.95rem;letter-spacing:.15em;color:var(--muted);margin-bottom:22px;text-transform:uppercase;}
  .usage{font-family:monospace;font-size:1rem;background:var(--input-bg);border:1px solid var(--border);border-radius:8px;padding:18px 22px;line-height:2;word-break:break-all;}
  .usage span{color:var(--red);}
  .stream-row{display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid var(--border);}
  .stream-row:last-child{border-bottom:none;}
  .badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:.8rem;letter-spacing:.06em;font-family:'Orbitron',monospace;}
  .badge.streaming{background:rgba(0,200,100,.15);color:#00a852;border:1px solid rgba(0,200,100,.3);}
  .badge.starting{background:rgba(255,152,0,.12);color:#c97800;border:1px solid rgba(255,152,0,.3);}
  .badge.error{background:rgba(227,25,55,.12);color:var(--red);border:1px solid rgba(227,25,55,.3);}
  .badge.done{background:var(--input-bg);color:var(--muted);border:1px solid var(--border);}
  .empty{color:var(--muted);font-size:1rem;font-style:italic;}
  a{color:var(--red);text-decoration:none;}a:hover{text-decoration:underline;}
  .env-row{display:flex;gap:28px;flex-wrap:wrap;margin-top:6px;}
  .env-item{font-family:monospace;font-size:.9rem;color:var(--muted);}
  .env-item b{color:var(--text);}
  /* Feed tab */
  .feed-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:22px;}
  .feed-controls input{flex:1;min-width:240px;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px 16px;font-family:monospace;font-size:1rem;}
  .feed-controls button{background:var(--red);color:white;border:0;border-radius:8px;padding:12px 20px;font-family:'Orbitron',monospace;letter-spacing:.08em;cursor:pointer;white-space:nowrap;font-size:.8rem;}
  .feed-status{color:var(--muted);font-size:.9rem;font-style:italic;margin-bottom:12px;min-height:1.4em;}
  .feed-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px;}
  .feed-card{background:var(--input-bg);border:1px solid var(--border);border-radius:10px;overflow:hidden;cursor:pointer;transition:border-color .15s;}
  .feed-card:hover{border-color:var(--red);}
  .feed-card-dismiss{background:none;border:none;color:var(--muted);font-size:14px;line-height:1;cursor:pointer;padding:0 0 0 6px;flex-shrink:0;}
  .feed-card-dismiss:hover{color:var(--red);}
  .feed-thumb{width:100%;aspect-ratio:16/9;object-fit:cover;background:var(--thumb-bg);display:block;}
  .feed-info{padding:10px 13px;}
  .feed-title{font-size:.9rem;line-height:1.35;color:var(--text);margin-bottom:5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
  .feed-dur{font-family:monospace;font-size:.78rem;color:var(--muted);}
  /* shared input style for start-stream row */
  #yt-id{flex:1;min-width:300px;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px 16px;font-family:monospace;font-size:1rem;}
  select{background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px 16px;font-family:monospace;font-size:1rem;}
  footer{margin-top:30px;color:var(--muted);font-size:.82rem;letter-spacing:.04em;text-align:center;max-width:1600px;line-height:1.6;}
  @keyframes warning-pulse {
    0% { transform: scale(1); opacity: 0.8; }
    50% { transform: scale(1.15); opacity: 1; }
    100% { transform: scale(1); opacity: 0.8; }
  }
</style>
</head>
<body>
<!-- Safety Warning Modal -->
<div id="safety-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); z-index:99999; justify-content:center; align-items:center; padding:20px;">
  <div style="background:var(--panel); border:2px solid var(--red); border-radius:16px; max-width:650px; width:100%; max-height:90vh; display:flex; flex-direction:column; box-shadow:0 0 40px rgba(227,25,55,0.25); overflow:hidden;">
    <!-- Modal Header -->
    <div style="background:rgba(227,25,55,0.1); padding:24px; border-bottom:1px solid var(--border); text-align:center;">
      <div style="font-size:2.2rem; margin-bottom:6px; display:inline-block; animation: warning-pulse 2s infinite ease-in-out;">⚠</div>
      <h2 style="font-family:'Orbitron',monospace; font-size:1.6rem; color:var(--red); letter-spacing:0.1em; text-transform:uppercase; margin:0;">Safety Warning</h2>
      <div style="font-family:'Orbitron',monospace; font-size:0.9rem; color:var(--text); letter-spacing:0.15em; margin-top:5px; font-weight:700;">USE ONLY WHEN PARKED</div>
    </div>
    
    <!-- Modal Body -->
    <div style="padding:24px; overflow-y:auto; font-size:0.95rem; line-height:1.6; color:var(--text); flex:1; display:flex; flex-direction:column; gap:16px;">
      <p style="font-weight:bold; text-align:center; color:#fff; font-size:1.1rem; margin-bottom:8px;">Do not use this application while driving or operating a vehicle of any kind.</p>
      
      <div style="display:flex; gap:12px; align-items:flex-start;">
        <span style="color:var(--red); font-size:1.2rem; line-height:1;">•</span>
        <p style="margin:0;">Watching video while driving is illegal in most countries and jurisdictions and poses a serious risk of death or injury to yourself and others.</p>
      </div>

      <div style="display:flex; gap:12px; align-items:flex-start;">
        <span style="color:var(--red); font-size:1.2rem; line-height:1;">•</span>
        <p style="margin:0;">You are solely responsible for complying with all applicable traffic laws, distracted-driving regulations, and any other laws in your jurisdiction.</p>
      </div>

      <div style="display:flex; gap:12px; align-items:flex-start;">
        <span style="color:var(--red); font-size:1.2rem; line-height:1;">•</span>
        <p style="margin:0;">This service is provided strictly "as-is" with no warranty of any kind — express or implied — including no guarantee of safety, fitness for purpose, or suitability for use in a vehicle.</p>
      </div>

      <div style="display:flex; gap:12px; align-items:flex-start;">
        <span style="color:var(--red); font-size:1.2rem; line-height:1;">•</span>
        <p style="margin:0;">This application and its creator are not affiliated with, endorsed by, or in any way connected to Tesla, Inc.</p>
      </div>

      <div style="display:flex; gap:12px; align-items:flex-start;">
        <span style="color:var(--red); font-size:1.2rem; line-height:1;">•</span>
        <p style="margin:0;">The creator of this application accepts no responsibility or liability of any kind for accidents, injuries, deaths, property damage, fines, penalties, legal proceedings, or any other consequences arising from your use of this application.</p>
      </div>

      <div style="display:flex; gap:12px; align-items:flex-start;">
        <span style="color:var(--red); font-size:1.2rem; line-height:1;">•</span>
        <p style="margin:0;">By continuing, you agree to indemnify and hold harmless the creator of this application from any and all claims, damages, losses, or liabilities resulting from your use of this application.</p>
      </div>
    </div>
    
    <!-- Modal Footer -->
    <div style="padding:24px; border-top:1px solid var(--border); background:rgba(0,0,0,0.25); display:flex; flex-direction:column; gap:14px; align-items:center; text-align:center;">
      <button id="accept-safety" style="background:var(--red); color:#fff; border:none; padding:14px 32px; font-family:'Orbitron',monospace; font-size:1rem; font-weight:900; letter-spacing:0.1em; border-radius:8px; cursor:pointer; transition:transform 0.15s, background-color 0.15s; width:100%; max-width:320px; box-shadow:0 4px 15px rgba(227,25,55,0.4);">
        I Understand & Accept
      </button>
      <p style="font-size:0.85rem; color:var(--muted); margin:0; max-width:550px; line-height:1.4;">
        By tapping "I Understand & Accept" you confirm that your vehicle is fully parked and stationary and that you agree to all terms stated above.
      </p>
    </div>
  </div>
</div>

<h1>OPENCARSTREAM</h1>
<p class="sub">A third-party streaming launcher for Tesla’s in-car browser</p>

<div class="tabs">
  <button class="tab-btn active" data-tab="stream">Stream</button>
  <button class="tab-btn" data-tab="feed">YouTube</button>
  <button class="tab-btn" data-tab="twitch">Twitch</button>
  <button class="tab-btn" data-tab="pluto">Pluto TV</button>
  <button class="tab-btn" data-tab="iptv">IPTV</button>
  <button class="tab-btn" data-tab="ace">Acestream</button>
  <button class="tab-btn" data-tab="local">Local Media</button>
  <button class="tab-btn" data-tab="info">Info</button>
</div>

<!-- ── Stream tab ── -->
<div class="tab-panel active" id="tab-stream">
  <div class="card">
    <h2>Start stream</h2>
    <p style="font-size:.85rem;color:var(--muted);margin-bottom:12px;">
      Paste any YouTube, Twitch, or X/Twitter video URL — or a YouTube video ID.
    </p>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <input id="yt-id" type="text" placeholder="URL or YouTube video ID">
      <div id="yt-mode-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="yt-quality-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="yt-profile-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="yt-sync-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
    </div>
    <div style="margin-top:10px;">
      <button id="go-stream"
              style="background:var(--red);color:white;border:0;border-radius:6px;padding:10px 16px;font-family:'Orbitron',monospace;letter-spacing:.08em;cursor:pointer;">
        OPEN STREAM
      </button>
    </div>
  </div>

  <div class="card">
    <h2>Active streams ({{stream_count}})</h2>
    {{streams_html}}
  </div>

  <div class="card">
    <h2>Configuration</h2>
    <div class="env-row">
      <div class="env-item">FPS <b>{{fps}}</b></div>
      <div class="env-item">Quality <b>{{quality}}</b></div>
      <div class="env-item">Resolution <b>{{width}}×{{height}}</b></div>
      <div class="env-item">MP4 <b>{{mp4_width}}×{{mp4_height}} @ {{mp4_bitrate}}</b></div>
      <div class="env-item">OGV <b>{{ogv_width}}×{{ogv_height}} @ {{ogv_fps}} fps</b></div>
      <div class="env-item">H.264 encoder <b>{{h264_encoder}}</b></div>
      <div class="env-item">HW accel <b>{{hwaccel}}</b></div>
      <div class="env-item">Max streams <b>{{max_streams}}</b></div>
    <div class="env-item">Audio start delay <b>{{audio_delay_ms}} ms</b></div>
    <div class="env-item">Subscriptions <b>{{subs_status}}</b></div>
    <div class="env-item">Pluto TV langs <b>{{pluto_langs}}</b></div>
    <div class="env-item">IPTV lists <b>{{iptv_status}}</b></div>
  </div>
</div>
</div>

<!-- ── Feed tab ── -->
<div class="tab-panel" id="tab-feed">
  <div class="card">
    <h2>Playback options</h2>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <div id="feed-mode-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="feed-quality-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="feed-profile-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="feed-sync-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
    </div>
  </div>

  <!-- Home feed panel -->
  <div class="card" id="home-card" style="display:none;">
    <h2>Home feed</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <button id="home-load" style="background:var(--red);color:white;border:0;border-radius:8px;padding:11px 20px;font-family:'Orbitron',monospace;font-size:.8rem;letter-spacing:.08em;cursor:pointer;">SHOW HOME FEED</button>
      <button id="home-refresh" style="display:none;background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:8px;padding:11px 18px;font-family:'Orbitron',monospace;font-size:.75rem;letter-spacing:.08em;cursor:pointer;">↺ REFRESH</button>
    </div>
    <div class="feed-status" id="home-status"></div>
    <div class="feed-grid" id="home-grid"></div>
    <div style="text-align:center;margin-top:14px;display:none;" id="home-more-wrap">
      <button id="home-more" style="background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:8px 20px;font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.08em;cursor:pointer;">LOAD MORE</button>
    </div>
  </div>

  <!-- Subscriptions panel (shown when subscriptions file is mounted) -->
  <div class="card" id="subs-card" style="display:none;">
    <h2>My subscriptions</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <button id="subs-load" style="background:var(--red);color:white;border:0;border-radius:8px;padding:11px 20px;font-family:'Orbitron',monospace;font-size:.8rem;letter-spacing:.08em;cursor:pointer;">SHOW SUBSCRIPTIONS</button>
      <input id="subs-filter" type="text" placeholder="Filter channels…"
             style="flex:1;min-width:180px;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-family:monospace;font-size:.95rem;display:none;">
    </div>
    <div class="feed-status" id="subs-status"></div>
    <div id="subs-list" style="display:flex;flex-direction:column;gap:0;max-height:480px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:0 4px;"></div>
  </div>

  <!-- YouTube search -->
  <div class="card">
    <h2>Search YouTube</h2>
    <div class="feed-controls">
      <input id="yt-search-input" type="text" placeholder="Search query…">
      <button id="yt-search-go">SEARCH</button>
    </div>
    <div class="feed-status" id="yt-search-status"></div>
    <div class="feed-grid" id="yt-search-grid"></div>
    <div style="text-align:center;margin-top:14px;display:none;" id="yt-search-more-wrap">
      <button id="yt-search-more" style="background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:8px 20px;font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.08em;cursor:pointer;">LOAD MORE</button>
    </div>
  </div>

  <!-- Manual channel lookup -->
  <div class="card">
    <h2 id="feed-card-title">Channel recent uploads</h2>
    <div class="feed-controls">
      <input id="feed-channel" type="text" placeholder="@channelhandle or channel URL">
      <button id="feed-go">LOAD FEED</button>
    </div>
    <div class="feed-status" id="feed-status"></div>
    <div class="feed-grid" id="feed-grid"></div>
    <div style="text-align:center;margin-top:14px;display:none;" id="feed-more-wrap">
      <button id="feed-more" style="background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:8px 20px;font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.08em;cursor:pointer;">LOAD MORE</button>
    </div>
  </div>
</div>

<!-- ── Twitch tab ── -->
<div class="tab-panel" id="tab-twitch">
  <div class="card">
    <h2>Playback options</h2>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <div id="twitch-mode-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="twitch-quality-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="twitch-profile-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="twitch-sync-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
    </div>
  </div>
  <div class="card">
    <h2>Live stream</h2>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <input id="twitch-live-channel" type="text" placeholder="channel name (e.g. xqc)" style="background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px 16px;font-family:monospace;font-size:1rem;">
      <div><button id="twitch-live-go" style="background:var(--red);color:white;border:0;border-radius:8px;padding:12px 20px;font-family:'Orbitron',monospace;letter-spacing:.08em;cursor:pointer;font-size:.8rem;">WATCH LIVE</button></div>
    </div>
  </div>
  <div class="card">
    <h2>VODs</h2>
    <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:14px;">
      <input id="twitch-vod-channel" type="text" placeholder="channel name" style="background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px 16px;font-family:monospace;font-size:1rem;">
      <div><button id="twitch-vod-go" style="background:var(--red);color:white;border:0;border-radius:8px;padding:12px 20px;font-family:'Orbitron',monospace;letter-spacing:.08em;cursor:pointer;font-size:.8rem;">LOAD VODS</button></div>
    </div>
    <div class="feed-status" id="twitch-vod-status"></div>
    <div class="feed-grid" id="twitch-vod-grid"></div>
    <div style="text-align:center;margin-top:14px;display:none;" id="twitch-vod-more-wrap">
      <button id="twitch-vod-more" style="background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:8px 20px;font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.08em;cursor:pointer;">LOAD MORE</button>
    </div>
  </div>
</div>

<!-- ── Pluto TV tab ── -->
<div class="tab-panel" id="tab-pluto">
  <div class="card">
    <h2>Playback options</h2>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <div id="pluto-mode-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="pluto-profile-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="pluto-sync-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <input id="pluto-filter" type="text" placeholder="Filter channels…"
             style="background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-family:monospace;">
    </div>
  </div>
  <div class="card">
    <h2>Channels</h2>
    <div id="pluto-lang-btns" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;"></div>
    <div class="feed-status" id="pluto-status">Open this tab to load channels.</div>
    <div id="pluto-list" style="max-height:520px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:0 10px 10px;"></div>
  </div>
</div>

<!-- ── IPTV tab ── -->
<div class="tab-panel" id="tab-iptv">
  <div class="card">
    <h2>Playback options</h2>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <div id="iptv-mode-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="iptv-quality-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="iptv-profile-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="iptv-sync-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
    </div>
  </div>
  <div class="card">
    <h2>IPTV lists</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <button id="iptv-prev"
              style="background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:8px 14px;font-family:'Orbitron',monospace;font-size:.9rem;cursor:pointer;">
        ◄
      </button>
      <div id="iptv-list-name"
           style="flex:1;min-width:180px;color:var(--text);font-size:.85rem;text-align:center;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--input-bg);">
        Select a list
      </div>
      <button id="iptv-next"
              style="background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:8px 14px;font-family:'Orbitron',monospace;font-size:.9rem;cursor:pointer;">
        ►
      </button>
      <button id="iptv-refresh"
              style="background:var(--red);color:white;border:0;border-radius:6px;padding:8px 14px;font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.08em;cursor:pointer;">
        REFRESH
      </button>
    </div>
    <input id="iptv-filter" type="text" placeholder="Filter streams..."
           style="width:100%;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-family:monospace;margin-bottom:12px;">
    <div class="feed-status" id="iptv-status">Open this tab to load IPTV lists.</div>
    <div id="iptv-streams"></div>
  </div>
</div>

<!-- ── Acestream tab ── -->
<div class="tab-panel" id="tab-ace">
  <div class="card">
    <h2>Playback options</h2>
    <div style="display:flex;flex-direction:column;gap:8px;">
      <div id="ace-mode-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="ace-quality-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="ace-profile-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="ace-sync-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
    </div>
  </div>
  <div class="card">
    <h2>Stream by content ID</h2>
    <p style="font-size:.85rem;color:var(--muted);margin-bottom:12px;">
      Enter an Acestream content ID (40-char hex) or a full
      <code style="color:var(--text);">acestream://</code> link.
      Your acestream-http-proxy must be running.
    </p>
    <div class="feed-controls">
      <input id="ace-id" type="text" placeholder="acestream://b08e… or content ID">
      <input id="ace-host" type="text" placeholder="Proxy host:port"
             style="max-width:200px;">
      <button id="ace-go">OPEN STREAM</button>
    </div>
  </div>
  <div class="card">
    <h2>Saved streams</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <input id="ace-save-name" type="text" placeholder="Name"
             style="flex:1;min-width:140px;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-family:monospace;">
      <input id="ace-save-id" type="text" placeholder="Content ID or acestream:// link"
             style="flex:2;min-width:220px;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-family:monospace;">
      <button id="ace-save-btn"
              style="background:var(--red);color:white;border:0;border-radius:6px;padding:8px 14px;font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.08em;cursor:pointer;">
        SAVE
      </button>
    </div>
    <div id="ace-saved-list"></div>
  </div>
</div>

<!-- ── Info tab ── -->
<div class="tab-panel" id="tab-local">
  <div class="card">
    <h2>Playback options</h2>
    <div style="display:flex;flex-direction:column;gap:10px;">
      <div id="local-mode-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="local-profile-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div id="local-sync-btns" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
      <div>
        <button id="local-refresh"
                style="background:var(--red);color:white;border:0;border-radius:6px;padding:8px 14px;font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.08em;cursor:pointer;">
          REFRESH LIST
        </button>
      </div>
    </div>
    <p style="font-size:.82rem;color:var(--muted);margin-top:12px;">
      Folder: <code style="color:var(--text);">{{local_media_dir}}</code>
    </p>
  </div>
  <div class="card">
    <h2>Video files</h2>
    <div class="feed-status" id="local-status">Open this tab to load local videos.</div>
    <div id="local-list"></div>
  </div>
</div>

<!-- ── Info tab ── -->
<div class="tab-panel" id="tab-info">
  <div class="card">
    <h2>API usage</h2>
    <div class="usage">
      GET /watch<span>?url=</span>https://youtube.com/watch?v=VIDEO_ID<br>
      GET /watch<span>?url=</span>https://www.twitch.tv/CHANNEL<br>
      GET /watch<span>?url=</span>https://x.com/user/status/ID<br>
      GET /watch<span>?url=</span>https://…<span>&amp;quality=720&amp;sync=1000</span><br>
      GET /feed<span>?channel=</span>@handle<span>&amp;limit=12</span>  → JSON video list<br>
      GET /local_media  → JSON local video list<br>
      GET /local_watch<span>?file=</span>relative/path.mp4<span>&amp;sync=1000</span><br>
      GET /iptv_lists  → JSON IPTV playlists from mounted folder<br>
      GET /iptv_streams<span>?list=</span>my-list<br>
      GET /subscriptions  → JSON channel list<br>
      GET /health   → JSON health check<br>
      GET /status   → JSON active streams
    </div>
  </div>
</div>

<footer>Tesla is a trademark of Tesla, Inc. OpenCarStream is unofficial and not affiliated with or endorsed by Tesla. YouTube is a trademark of Google LLC, Twitch is a trademark of Twitch Interactive, Inc., and X/Twitter is a trademark of X Corp.; OpenCarStream is not affiliated with or endorsed by any of them.</footer>
<p id="weather-text" style="margin-top:10px;color:var(--muted);font-size:.85rem;text-align:center;"></p>

<script>
  function stopStream(sid) {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/stop_stream?sid=" + encodeURIComponent(sid), true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      window.location.reload();
    };
    xhr.send();
  }
</script>
<script>
(function () {
  // ── Safety Warning Modal for Tesla ──
  var isTesla = /tesla/i.test(navigator.userAgent);
  var safetyAccepted = sessionStorage.getItem("safetyAccepted") === "true";
  if (isTesla && !safetyAccepted) {
    var modal = document.getElementById("safety-modal");
    if (modal) {
      modal.style.display = "flex";
      var acceptBtn = document.getElementById("accept-safety");
      if (acceptBtn) {
        acceptBtn.addEventListener("click", function () {
          sessionStorage.setItem("safetyAccepted", "true");
          modal.style.display = "none";
        });
      }
    }
  }

  // ── Tab switching ──
  var tabBtns = document.querySelectorAll(".tab-btn");
  var tabPanels = document.querySelectorAll(".tab-panel");
  Array.prototype.forEach.call(tabBtns, function (btn) {
    btn.addEventListener("click", function () {
      var target = btn.getAttribute("data-tab");
      Array.prototype.forEach.call(tabBtns, function (b) { b.classList.remove("active"); });
      Array.prototype.forEach.call(tabPanels, function (p) { p.classList.remove("active"); });
      btn.classList.add("active");
      var panel = document.getElementById("tab-" + target);
      if (panel) panel.classList.add("active");
    });
  });

  try {
  // ── Shared utilities ──
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function fmtDuration(secs) {
    var s = parseInt(secs, 10);
    if (!s || isNaN(s)) return "";
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (h > 0) return h + ":" + pad(m) + ":" + pad(sec);
    return m + ":" + pad(sec);
  }
  function escHtml(s) {
    return (s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  // ── Button group helper ──
  function createButtonGroup(containerId, options, defaultValue) {
    var container = document.getElementById(containerId);
    var state = { value: defaultValue || "" };

    options.forEach(function (opt) {
      var btn = document.createElement("button");
      btn.setAttribute("data-value", opt.value);
      btn.textContent = opt.label;
      btn.style.cssText = "font-family:'Orbitron',monospace;font-size:.7rem;" +
        "letter-spacing:.08em;padding:6px 12px;border-radius:6px;" +
        "border:1px solid var(--border);cursor:pointer;";
      btn.addEventListener("click", function () {
        state.value = opt.value;
        container.querySelectorAll("button").forEach(function (b) {
          b.style.background = b.getAttribute("data-value") === state.value
            ? "var(--red)" : "transparent";
          b.style.color = b.getAttribute("data-value") === state.value
            ? "#fff" : "var(--muted)";
        });
      });
      container.appendChild(btn);
    });

    // Set initial active state
    container.querySelectorAll("button").forEach(function (b) {
      b.style.background = b.getAttribute("data-value") === state.value
        ? "var(--red)" : "transparent";
      b.style.color = b.getAttribute("data-value") === state.value
        ? "#fff" : "var(--muted)";
    });

    return state;
  }

  // ── Mode button options (shared across tabs) ──
  var modeOptions = [
    { value: "ogv",    label: "OGV (Tesla)" },
    { value: "mp4",    label: "MP4 (smooth)" },
    { value: "mjpeg",  label: "MJPEG fallback" },
    { value: "audio",  label: "Audio only" }
  ];
  var isTesla = /tesla/i.test(navigator.userAgent);
  var defaultMode = isTesla ? "ogv" : "mp4";
  var qualityOptions = [
    { value: "auto", label: "SRC AUTO" },
    { value: "2160", label: "4K" },
    { value: "1440", label: "1440p" },
    { value: "1080", label: "1080p" },
    { value: "720", label: "720p" },
    { value: "480", label: "480p" },
    { value: "360", label: "360p" },
    { value: "240", label: "240p" },
    { value: "144", label: "144p" }
  ];
  var profileOptions = [
    { value: "auto", label: "OUT AUTO" },
    { value: "2160", label: "OUT 4K" },
    { value: "1440", label: "OUT 1440" },
    { value: "1080", label: "OUT 1080" },
    { value: "720", label: "OUT 720" },
    { value: "480", label: "OUT 480" },
    { value: "360", label: "OUT 360" }
  ];

  function autoQualityForNetwork(mode) {
    var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!c) return mode === "ogv" ? "720" : "1080";
    if (c.saveData) return "1440";
    var down = Number(c.downlink || 0);
    if (!down) return mode === "ogv" ? "720" : "1080";
    if (down >= 35) return "2160";
    if (down >= 18) return "1440";
    if (down >= 9) return "1080";
    if (down >= 4.5) return "720";
    if (down >= 2.2) return "480";
    return "1440";
  }

  // ── Stream tab ──
  var idInput    = document.getElementById("yt-id");
  var goButton   = document.getElementById("go-stream");

  var modeSel = createButtonGroup("yt-mode-btns", modeOptions, defaultMode);

  var qualitySel = createButtonGroup("yt-quality-btns", qualityOptions, "auto");
  var profileSel = createButtonGroup("yt-profile-btns", profileOptions, "auto");

  var syncSel = createButtonGroup("yt-sync-btns", [
    { value: "0", label: "0s" },
    { value: "500", label: "0.5s" },
    { value: "1000", label: "1s" },
    { value: "1500", label: "1.5s" },
    { value: "2000", label: "2s" },
    { value: "2500", label: "2.5s" },
    { value: "3000", label: "3s" },
    { value: "3500", label: "3.5s" },
    { value: "4000", label: "4s" }
  ], "{{audio_delay_ms}}");

  function buildWatchUrl(videoUrl, quality, sync, mode, profile) {
    var resolvedQuality = quality === "auto" ? autoQualityForNetwork(mode) : quality;
    var resolvedProfile = profile === "auto" ? autoQualityForNetwork(mode) : profile;
    var target = "/watch?url=" + encodeURIComponent(videoUrl);
    if (resolvedQuality) target += "&quality=" + encodeURIComponent(resolvedQuality);
    if (sync)    target += "&sync="    + encodeURIComponent(sync);
    if (mode) target += "&mode=" + encodeURIComponent(mode);
    if (resolvedProfile && mode !== "audio") target += "&profile=" + encodeURIComponent(resolvedProfile);
    if (quality === "auto" || profile === "auto") target += "&auto=1";
    return target;
  }

  function resolveInputUrl(raw) {
    // Full URL (YouTube, Twitch, X/Twitter, etc.) — pass through
    if (/^https?:[/][/]/i.test(raw)) return raw;
    // Bare YouTube video ID (11 alphanum chars)
    if (/^[A-Za-z0-9_-]{11}$/.test(raw)) {
      return "https://www.youtube.com/watch?v=" + raw;
    }
    // Twitch channel shorthand: twitch:channel
    if (/^twitch:/i.test(raw)) {
      return "https://www.twitch.tv/" + raw.slice(7);
    }
    // Fallback: treat as YouTube ID anyway
    return "https://www.youtube.com/watch?v=" + raw;
  }

  function OpenCarStream() {
    var raw = (idInput.value || "").trim();
    if (!raw) { idInput.focus(); return; }
    window.location.href = buildWatchUrl(
      resolveInputUrl(raw), qualitySel.value, syncSel.value, modeSel.value, profileSel.value
    );
  }

  goButton.addEventListener("click", OpenCarStream);
  idInput.addEventListener("keydown", function (e) {
    if ((e.key || "") === "Enter" || e.keyCode === 13) OpenCarStream();
  });

  // ── Twitch tab ──
  var twitchLiveCh   = document.getElementById("twitch-live-channel");
  var twitchLiveGo   = document.getElementById("twitch-live-go");
  var twitchVodCh    = document.getElementById("twitch-vod-channel");
  var twitchVodGo    = document.getElementById("twitch-vod-go");
  var twitchVodSt    = document.getElementById("twitch-vod-status");
  var twitchVodGrid  = document.getElementById("twitch-vod-grid");

  var twitchMode = createButtonGroup("twitch-mode-btns", modeOptions, defaultMode);

  var twitchQuality = createButtonGroup("twitch-quality-btns", qualityOptions, "auto");
  var twitchProfile = createButtonGroup("twitch-profile-btns", profileOptions, "auto");

  var twitchSync = createButtonGroup("twitch-sync-btns", [
    { value: "0", label: "0s" },
    { value: "500", label: "0.5s" },
    { value: "1000", label: "1s" },
    { value: "1500", label: "1.5s" },
    { value: "2000", label: "2s" },
    { value: "2500", label: "2.5s" },
    { value: "3000", label: "3s" },
    { value: "3500", label: "3.5s" },
    { value: "4000", label: "4s" }
  ], "{{audio_delay_ms}}");

  twitchLiveGo.addEventListener("click", function () {
    var ch = (twitchLiveCh.value || "").trim().replace(/^@/, "");
    if (!ch) { twitchLiveCh.focus(); return; }
    var url = "https://www.twitch.tv/" + ch;
    window.location.href = buildWatchUrl(url, twitchQuality.value, twitchSync.value, twitchMode.value, twitchProfile.value);
  });
  twitchLiveCh.addEventListener("keydown", function (e) {
    if ((e.key || "") === "Enter" || e.keyCode === 13) twitchLiveGo.click();
  });

  var twitchVodMoreWrap = document.getElementById("twitch-vod-more-wrap");
  var twitchVodMoreBtn  = document.getElementById("twitch-vod-more");
  var twitchVodLimit    = 12;

  function loadTwitchVods(append) {
    var ch = (twitchVodCh.value || "").trim().replace(/^@/, "");
    if (!ch) { twitchVodCh.focus(); return; }
    if (!append) {
      twitchVodLimit = 12;
      twitchVodGrid.innerHTML = "";
      twitchVodMoreWrap.style.display = "none";
    }
    twitchVodSt.textContent = "Loading VODs…";
    var url = "https://www.twitch.tv/" + ch + "/videos";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/feed?channel=" + encodeURIComponent(url) + "&limit=" + twitchVodLimit, true);
    xhr.timeout = 30000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        twitchVodSt.textContent = "Failed to parse response."; return;
      }
      if (data.error) { twitchVodSt.textContent = "Error: " + data.error; return; }
      var videos = data.videos || [];
      if (!videos.length) { twitchVodSt.textContent = "No VODs found."; twitchVodMoreWrap.style.display = "none"; return; }
      if (append) {
        var existing = twitchVodGrid.querySelectorAll(".feed-card").length;
        videos = videos.slice(existing);
      }
      videos.forEach(function (v) {
        var card = document.createElement("div");
        card.className = "feed-card";
        var dur = fmtDuration(v.duration);
        card.innerHTML =
          '<img class="feed-thumb" src="' + (v.thumb || "") + '" loading="lazy" alt="">' +
          '<div class="feed-info">' +
          '<div class="feed-title">' + escHtml(v.title) + '</div>' +
          (dur ? '<div class="feed-dur">' + escHtml(dur) + '</div>' : '') +
          '</div>';
        card.addEventListener("click", function () {
          window.location.href = buildWatchUrl(v.url, twitchQuality.value, twitchSync.value, twitchMode.value, twitchProfile.value);
        });
        twitchVodGrid.appendChild(card);
      });
      twitchVodSt.textContent = twitchVodGrid.querySelectorAll(".feed-card").length + " VODs";
      twitchVodMoreWrap.style.display = "block";
    };
    xhr.send();
  }

  twitchVodGo.addEventListener("click", function () { loadTwitchVods(false); });
  twitchVodMoreBtn.addEventListener("click", function () {
    twitchVodLimit += 12;
    loadTwitchVods(true);
  });
  twitchVodCh.addEventListener("keydown", function (e) {
    if ((e.key || "") === "Enter" || e.keyCode === 13) loadTwitchVods(false);
  });

  // ── Pluto TV tab ──
  var plutoFilter   = document.getElementById("pluto-filter");
  var plutoStatus   = document.getElementById("pluto-status");
  var plutoList     = document.getElementById("pluto-list");
  var plutoLangBtns = document.getElementById("pluto-lang-btns");

  var plutoMode = createButtonGroup("pluto-mode-btns", modeOptions, defaultMode);
  var plutoProfile = createButtonGroup("pluto-profile-btns", profileOptions, "auto");

  var plutoSync = createButtonGroup("pluto-sync-btns", [
    { value: "0", label: "0s" },
    { value: "500", label: "0.5s" },
    { value: "1000", label: "1s" },
    { value: "1500", label: "1.5s" },
    { value: "2000", label: "2s" },
    { value: "2500", label: "2.5s" },
    { value: "3000", label: "3s" },
    { value: "3500", label: "3.5s" },
    { value: "4000", label: "4s" }
  ], "{{audio_delay_ms}}");

  var plutoByLang   = {};   // { lang: [channels] }
  var plutoMetaByLang = {}; // { lang: { country: "...", refresh_at: n } }
  var plutoActiveLang = null;
  var plutoLangs    = {{pluto_langs_json}};

  function renderPluto(channels) {
    plutoList.innerHTML = "";
    var lastCat = null;
    channels.forEach(function (ch) {
      if (ch.category && ch.category !== lastCat) {
        lastCat = ch.category;
        var hdr = document.createElement("div");
        hdr.style.cssText = "font-family:'Orbitron',monospace;font-size:.7rem;" +
          "letter-spacing:.12em;color:var(--muted);padding:10px 0 4px;" +
          "text-transform:uppercase;border-top:1px solid var(--border);margin-top:4px;";
        hdr.textContent = ch.category;
        plutoList.appendChild(hdr);
      }
      var row = document.createElement("div");
      row.className = "stream-row";
      row.style.cursor = "pointer";
      row.innerHTML =
        '<span style="font-size:.95rem;">' + escHtml(ch.name) + '</span>' +
        '<span style="font-family:monospace;font-size:.75rem;color:var(--muted);">LIVE →</span>';
      row.addEventListener("click", function () {
        if (ch.id && plutoActiveLang) {
          var plutoWatchUrl = "/pluto_watch?lang=" + encodeURIComponent(plutoActiveLang) +
            "&id=" + encodeURIComponent(ch.id) +
            "&sync=" + encodeURIComponent(plutoSync.value);
          if (plutoMode.value) plutoWatchUrl += "&mode=" + encodeURIComponent(plutoMode.value);
          if (plutoProfile.value) plutoWatchUrl += "&profile=" + encodeURIComponent(plutoProfile.value === "auto" ? autoQualityForNetwork(plutoMode.value) : plutoProfile.value);
          window.location.href = plutoWatchUrl;
          return;
        }
        window.location.href = buildWatchUrl(ch.url, "auto", plutoSync.value, plutoMode.value, plutoProfile.value);
      });
      plutoList.appendChild(row);
    });
  }

  function applyPlutoFilter() {
    var all = plutoByLang[plutoActiveLang] || [];
    var meta = plutoMetaByLang[plutoActiveLang] || {};
    var q = (plutoFilter.value || "").toLowerCase().trim();
    var filtered = q
      ? all.filter(function (c) {
          return c.name.toLowerCase().indexOf(q) !== -1 ||
                 c.category.toLowerCase().indexOf(q) !== -1;
        })
      : all;
    renderPluto(filtered);
    var activeTag = plutoActiveLang ? plutoActiveLang.toUpperCase() : "?";
    var countryTag = meta.country ? (" / " + meta.country.toUpperCase()) : "";
    var regionTag = meta.region ? (" req:" + meta.region.toUpperCase()) : "";
    var sameAs = "";
    var activeSig = all.map(function (c) { return c.id || c.name; }).join("|");
    if (activeSig) {
      Object.keys(plutoByLang).forEach(function (otherLang) {
        if (sameAs || otherLang === plutoActiveLang) return;
        var otherSig = (plutoByLang[otherLang] || [])
          .map(function (c) { return c.id || c.name; })
          .join("|");
        if (otherSig && otherSig === activeSig) {
          sameAs = otherLang.toUpperCase();
        }
      });
    }
    var sameNote = sameAs ? (" · same lineup as " + sameAs + " in your region") : "";
    plutoStatus.textContent =
      "[" + activeTag + countryTag + regionTag + "] " +
      filtered.length + (q ? " of " + all.length : "") +
      " channels (no account required)" + sameNote;
  }

  function switchPlutoLang(lang) {
    plutoActiveLang = lang;
    // Update button styles
    plutoLangBtns.querySelectorAll("button").forEach(function (b) {
      b.style.background = b.getAttribute("data-lang") === lang
        ? "var(--red)" : "transparent";
      b.style.color = b.getAttribute("data-lang") === lang
        ? "#fff" : "var(--muted)";
    });
    if (plutoByLang[lang]) {
      applyPlutoFilter();
      return;
    }
    plutoStatus.textContent = "Loading " + lang.toUpperCase() + " channels\u2026";
    plutoList.innerHTML = "";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/pluto_channels?lang=" + encodeURIComponent(lang), true);
    xhr.timeout = 15000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        plutoStatus.textContent = "Failed to load channels."; return;
      }
      if (data.error) { plutoStatus.textContent = "Error: " + data.error; return; }
      plutoByLang[lang] = data.channels || [];
      plutoMetaByLang[lang] = {
        country: data.country || "",
        region: data.region || "",
        xff: data.xff || "",
        refresh_at: data.refresh_at || 0
      };
      if (plutoActiveLang === lang) applyPlutoFilter();
    };
    xhr.send();
  }

  // Build language toggle buttons
  plutoLangs.forEach(function (lang) {
    var btn = document.createElement("button");
    btn.setAttribute("data-lang", lang);
    btn.textContent = lang.toUpperCase();
    btn.style.cssText = "font-family:'Orbitron',monospace;font-size:.7rem;" +
      "letter-spacing:.1em;padding:6px 14px;border-radius:6px;" +
      "border:1px solid var(--border);background:transparent;" +
      "color:var(--muted);cursor:pointer;";
    btn.addEventListener("click", function () { switchPlutoLang(lang); });
    plutoLangBtns.appendChild(btn);
  });

  // Load first language when Pluto tab is first opened
  var plutoOpened = false;
  document.querySelector('[data-tab="pluto"]').addEventListener("click", function () {
    if (plutoOpened) return;
    plutoOpened = true;
    switchPlutoLang(plutoLangs[0]);
  });

  plutoFilter.addEventListener("input", applyPlutoFilter);

  // ── IPTV tab ──
  var iptvPrevBtn   = document.getElementById("iptv-prev");
  var iptvNextBtn   = document.getElementById("iptv-next");
  var iptvListName  = document.getElementById("iptv-list-name");
  var iptvRefreshBtn= document.getElementById("iptv-refresh");
  var iptvFilter    = document.getElementById("iptv-filter");
  var iptvStatus    = document.getElementById("iptv-status");
  var iptvStreamsEl = document.getElementById("iptv-streams");

  var iptvMode = createButtonGroup("iptv-mode-btns", modeOptions, defaultMode);

  var iptvQuality = createButtonGroup("iptv-quality-btns", qualityOptions, "auto");
  var iptvProfile = createButtonGroup("iptv-profile-btns", profileOptions, "auto");

  var iptvSync = createButtonGroup("iptv-sync-btns", [
    { value: "0", label: "0s" },
    { value: "500", label: "0.5s" },
    { value: "1000", label: "1s" },
    { value: "1500", label: "1.5s" },
    { value: "2000", label: "2s" },
    { value: "2500", label: "2.5s" },
    { value: "3000", label: "3s" },
    { value: "3500", label: "3.5s" },
    { value: "4000", label: "4s" }
  ], "{{audio_delay_ms}}");

  var iptvLists = [];
  var iptvStreams = [];
  var iptvCurrentIndex = 0;

  function selectedIptvListId() {
    if (!iptvLists.length || iptvCurrentIndex < 0) return "";
    return iptvLists[iptvCurrentIndex].id || "";
  }

  function updateIptvListDisplay() {
    if (!iptvLists.length) {
      iptvListName.textContent = "No .m3u lists found";
      iptvListName.style.color = "var(--muted)";
      iptvPrevBtn.disabled = true;
      iptvNextBtn.disabled = true;
      iptvPrevBtn.style.opacity = "0.3";
      iptvNextBtn.style.opacity = "0.3";
      return;
    }
    iptvPrevBtn.disabled = false;
    iptvNextBtn.disabled = false;
    iptvPrevBtn.style.opacity = "1";
    iptvNextBtn.style.opacity = "1";
    var current = iptvLists[iptvCurrentIndex];
    iptvListName.textContent = current.name + " (" + (iptvCurrentIndex + 1) + "/" + iptvLists.length + ")";
    iptvListName.style.color = "var(--text)";
  }

  function renderIptvLists() {
    updateIptvListDisplay();
  }

  iptvPrevBtn.addEventListener("click", function () {
    if (!iptvLists.length) return;
    iptvCurrentIndex = (iptvCurrentIndex - 1 + iptvLists.length) % iptvLists.length;
    updateIptvListDisplay();
    loadIptvStreams();
  });

  iptvNextBtn.addEventListener("click", function () {
    if (!iptvLists.length) return;
    iptvCurrentIndex = (iptvCurrentIndex + 1) % iptvLists.length;
    updateIptvListDisplay();
    loadIptvStreams();
  });

  function renderIptvStreams(list) {
    var q = (iptvFilter.value || "").toLowerCase().trim();
    iptvStreamsEl.innerHTML = "";
    var visible = iptvStreams.filter(function (item) {
      if (!q) return true;
      return (item.name || "").toLowerCase().indexOf(q) !== -1;
    });
    if (!visible.length) {
      iptvStreamsEl.innerHTML = '<p class="empty">No streams match this filter.</p>';
      return;
    }
    visible.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "stream-row";
      row.style.cursor = "pointer";

      var leftSpan = document.createElement("span");
      leftSpan.style.cssText = "display:flex;align-items:center;gap:10px;font-size:.95rem;";

      if (item.logo) {
        var logoImg = document.createElement("img");
        logoImg.src = item.logo;
        logoImg.style.cssText = "width:28px;height:28px;border-radius:4px;flex-shrink:0;object-fit:contain;background-color:rgba(255,255,255,0.1);";
        logoImg.onerror = function() {
          logoImg.style.display = "none";
        };
        leftSpan.appendChild(logoImg);
      }

      var textSpan = document.createElement("span");
      textSpan.textContent = item.name || item.url;
      leftSpan.appendChild(textSpan);

      var rightSpan = document.createElement("span");
      rightSpan.style.cssText = "font-family:monospace;font-size:.75rem;color:var(--muted);";
      rightSpan.textContent = "OPEN \u2192";

      row.appendChild(leftSpan);
      row.appendChild(rightSpan);

      row.addEventListener("click", function () {
        window.location.href = buildWatchUrl(item.url, iptvQuality.value, iptvSync.value, iptvMode.value, iptvProfile.value);
      });
      iptvStreamsEl.appendChild(row);
    });
    iptvStatus.textContent = visible.length + " streams in " + list.name;
  }

  function loadIptvStreams() {
    var listId = selectedIptvListId();
    if (!listId) {
      iptvStatus.textContent = "No IPTV list selected.";
      iptvStreamsEl.innerHTML = "";
      return;
    }
    iptvStatus.textContent = "Loading IPTV streams...";
    iptvStreamsEl.innerHTML = "";
    iptvRefreshBtn.disabled = true;

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/iptv_streams?list=" + encodeURIComponent(listId), true);
    xhr.timeout = 15000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      iptvRefreshBtn.disabled = false;
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        iptvStatus.textContent = "Failed to parse response."; return;
      }
      if (data.error) { iptvStatus.textContent = "Error: " + data.error; return; }
      iptvStreams = data.streams || [];
      if (!iptvStreams.length) {
        iptvStatus.textContent = "No streams found in this list.";
        iptvStreamsEl.innerHTML = '<p class="empty">This list has no playable entries.</p>';
        return;
      }
      iptvFilter.value = "";
      renderIptvStreams(data.list || {name: "selected list"});
    };
    xhr.send();
  }

  function loadIptvLists(autoloadFirst) {
    iptvStatus.textContent = "Scanning IPTV lists folder...";
    iptvStreamsEl.innerHTML = "";
    iptvRefreshBtn.disabled = true;
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/iptv_lists", true);
    xhr.timeout = 10000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      iptvRefreshBtn.disabled = false;
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        iptvStatus.textContent = "Failed to parse response."; return;
      }
      if (data.error) { iptvStatus.textContent = "Error: " + data.error; return; }
      iptvLists = data.lists || [];
      renderIptvLists();
      if (!iptvLists.length) {
        iptvStatus.textContent = "No .m3u or .m3u8 files found.";
        return;
      }
      iptvStatus.textContent = iptvLists.length + " IPTV lists found";
      if (autoloadFirst) {
        iptvCurrentIndex = 0;
        updateIptvListDisplay();
        loadIptvStreams();
      }
    };
    xhr.send();
  }

  iptvRefreshBtn.addEventListener("click", function () { loadIptvLists(false); });
  iptvFilter.addEventListener("input", function () {
    if (!iptvStreams.length) return;
    var selected = iptvLists.find(function (item) { return item.id === selectedIptvListId(); }) || {name: "selected list"};
    renderIptvStreams(selected);
  });
  var iptvOpened = false;
  document.querySelector('[data-tab="iptv"]').addEventListener("click", function () {
    if (iptvOpened) return;
    iptvOpened = true;
    loadIptvLists(true);
  });

  // ── Home feed (inside YouTube tab) ──
  var homeCard     = document.getElementById("home-card");
  var homeGrid     = document.getElementById("home-grid");
  var homeStatus   = document.getElementById("home-status");
  var homeLoad     = document.getElementById("home-load");
  var homeRefresh  = document.getElementById("home-refresh");
  var homeMoreWrap = document.getElementById("home-more-wrap");
  var homeMoreBtn  = document.getElementById("home-more");
  var homeAllVideos = [];
  var homeShown    = 0;
  var HOME_PAGE    = 16;

  // Home feed reuses the feed tab's quality/sync selectors (defined below)

  function makeHomeCard(v) {
    var card = document.createElement("div");
    card.className = "feed-card";
    var dur = fmtDuration(v.duration);
    var dateStr = "";
    if (v.upload_date && v.upload_date.length === 8 && v.upload_date !== "NA") {
      dateStr = v.upload_date.slice(0,4) + "-" + v.upload_date.slice(4,6) + "-" + v.upload_date.slice(6,8);
    }
    card.innerHTML =
      '<img class="feed-thumb" src="' + (v.thumb || "") + '" loading="lazy" alt="">' +
      '<div class="feed-info">' +
      '<div style="display:flex;align-items:flex-start;gap:4px;">' +
      '<div class="feed-title" style="flex:1;">' + escHtml(v.title) + '</div>' +
      '<button class="feed-card-dismiss" title="Dismiss">✕</button>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">' +
      '<div style="font-size:.75rem;color:var(--red);font-family:Orbitron,monospace;letter-spacing:.04em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%;">' + escHtml(v.channel || "") + '</div>' +
      '<div style="font-family:monospace;font-size:.75rem;color:var(--muted);white-space:nowrap;">' +
        (dateStr ? '<span style="color:var(--text);">' + escHtml(dateStr) + '</span>' + (dur ? ' · ' : '') : '') +
        (dur ? escHtml(dur) : '') +
      '</div>' +
      '</div></div>';
    card.querySelector(".feed-card-dismiss").addEventListener("click", function (e) {
      e.stopPropagation();
      card.remove();
    });
    card.addEventListener("click", function () {
      window.location.href = buildWatchUrl(v.url, feedQuality.value, feedSync.value, feedMode.value, feedProfile.value);
    });
    return card;
  }

  function renderHomePage() {
    var next = homeAllVideos.slice(homeShown, homeShown + HOME_PAGE);
    next.forEach(function (v) { homeGrid.appendChild(makeHomeCard(v)); });
    homeShown += next.length;
    homeMoreWrap.style.display = homeShown < homeAllVideos.length ? "block" : "none";
  }

  function loadHomeFeed(force) {
    homeStatus.textContent = "Loading…";
    homeLoad.style.display = "none";
    homeRefresh.style.display = "none";
    homeMoreWrap.style.display = "none";
    homeGrid.innerHTML = "";
    homeAllVideos = [];
    homeShown = 0;
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/subscriptions_feed" + (force ? "?force=1" : ""), true);
    xhr.timeout = 300000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      homeRefresh.style.display = "";
      var data;
      try { data = JSON.parse(xhr.responseText); } catch(e) {
        homeStatus.textContent = "Failed to parse response."; return;
      }
      if (data.error) { homeStatus.textContent = "Error: " + data.error; return; }
      var videos = data.videos || [];
      if (!videos.length) { homeStatus.textContent = "No videos found."; return; }
      // Server already sorted: dated newest-first, then undated by channel position.
      // Re-sort on client in case cache was built by an older version.
      homeAllVideos = videos;
      var cachedNote = data.cached ? " · cached" : "";
      var builtDate  = data.built_at ? new Date(data.built_at * 1000).toLocaleTimeString() : "";
      homeStatus.textContent = videos.length + " videos" + cachedNote + (builtDate ? " · updated " + builtDate : "");
      renderHomePage();
    };
    xhr.send();
  }

  homeMoreBtn.addEventListener("click", renderHomePage);
  homeLoad.addEventListener("click", function () { loadHomeFeed(false); });
  homeRefresh.addEventListener("click", function () { loadHomeFeed(true); });

  // ── Feed tab ──
  var feedChannel  = document.getElementById("feed-channel");
  var feedGoBtn    = document.getElementById("feed-go");
  var feedStatus   = document.getElementById("feed-status");
  var feedGrid     = document.getElementById("feed-grid");
  var feedCardTitle= document.getElementById("feed-card-title");

  var feedMode = createButtonGroup("feed-mode-btns", modeOptions, defaultMode);

  var feedQuality = createButtonGroup("feed-quality-btns", qualityOptions, "auto");
  var feedProfile = createButtonGroup("feed-profile-btns", profileOptions, "auto");

  var feedSync = createButtonGroup("feed-sync-btns", [
    { value: "0", label: "0s" },
    { value: "500", label: "0.5s" },
    { value: "1000", label: "1s" },
    { value: "1500", label: "1.5s" },
    { value: "2000", label: "2s" },
    { value: "2500", label: "2.5s" },
    { value: "3000", label: "3s" },
    { value: "3500", label: "3.5s" },
    { value: "4000", label: "4s" }
  ], "{{audio_delay_ms}}");

  // Subscriptions
  var subsCard   = document.getElementById("subs-card");
  var subsLoad   = document.getElementById("subs-load");
  var subsFilter = document.getElementById("subs-filter");
  var subsStatus = document.getElementById("subs-status");
  var subsList   = document.getElementById("subs-list");
  var allChannels = [];

  // Probe whether subscriptions.json is mounted; show subscription + home cards if so
  (function probeSubscriptions() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/subscriptions", true);
    xhr.timeout = 2000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status !== 503) {
        subsCard.style.display = "block";
        homeCard.style.display = "block";
      }
    };
    xhr.send();
  })();

  // ── Favorites (persisted server-side in /config/favorites.json) ─────────
  var serverFavs = [];  // set of URLs, loaded once and kept in sync

  function fetchFavs(cb) {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/favorites", true);
    xhr.timeout = 5000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      try { serverFavs = JSON.parse(xhr.responseText).favorites || []; } catch(e) { serverFavs = []; }
      if (cb) cb();
    };
    xhr.send();
  }

  function toggleFav(url, isFav, cb) {
    var xhr = new XMLHttpRequest();
    if (isFav) {
      xhr.open("DELETE", "/favorites?url=" + encodeURIComponent(url), true);
      xhr.send();
    } else {
      xhr.open("POST", "/favorites", true);
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(JSON.stringify({url: url}));
    }
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      try { serverFavs = JSON.parse(xhr.responseText).favorites || []; } catch(e) {}
      if (cb) cb();
    };
  }

  function sortWithFavs(channels) {
    return channels.slice().sort(function(a, b) {
      var fa = serverFavs.indexOf(a.url) !== -1 ? 1 : 0;
      var fb = serverFavs.indexOf(b.url) !== -1 ? 1 : 0;
      if (fa !== fb) return fb - fa;
      return a.name.localeCompare(b.name);
    });
  }

  function renderChannelList(channels) {
    subsList.innerHTML = "";
    var sorted = sortWithFavs(channels);
    sorted.forEach(function (ch) {
      var isFav = serverFavs.indexOf(ch.url) !== -1;
      var row = document.createElement("div");
      row.className = "stream-row";
      row.style.cursor = "pointer";
      row.style.alignItems = "center";

      var star = document.createElement("span");
      star.textContent = isFav ? "★" : "☆";
      star.title = isFav ? "Remove from favorites" : "Add to favorites";
      star.style.cssText = "font-size:1.2rem;margin-right:8px;flex-shrink:0;color:" + (isFav ? "#f5c518" : "var(--muted)") + ";cursor:pointer;user-select:none;";
      star.addEventListener("click", function (e) {
        e.stopPropagation();
        var wasFav = serverFavs.indexOf(ch.url) !== -1;
        toggleFav(ch.url, wasFav, function () { applyFilter(); });
      });

      var label = document.createElement("a");
      label.style.cssText = "color:var(--text);font-size:.95rem;flex:1;";
      label.textContent = ch.name;

      var arrow = document.createElement("span");
      arrow.style.cssText = "font-family:monospace;font-size:.75rem;color:var(--muted);";
      arrow.textContent = "LOAD →";

      row.appendChild(star);
      var logoUrl = ch.logo || ch.thumbnail;
      if (logoUrl) {
        var logoImg = document.createElement("img");
        logoImg.src = logoUrl;
        logoImg.style.cssText = "width:28px;height:28px;border-radius:50%;margin-right:10px;flex-shrink:0;object-fit:cover;background-color:rgba(255,255,255,0.1);";
        logoImg.onerror = function() {
          logoImg.style.display = "none";
        };
        row.appendChild(logoImg);
      }
      row.appendChild(label);
      row.appendChild(arrow);

      row.addEventListener("click", function () {
        feedChannel.value = ch.url;
        feedCardTitle.textContent = ch.name + " — recent uploads";
        loadFeed();
        feedGrid.scrollIntoView({behavior: "smooth", block: "start"});
      });
      subsList.appendChild(row);
    });
  }

  function applyFilter() {
    var q = (subsFilter.value || "").toLowerCase().trim();
    if (!q) { renderChannelList(allChannels); return; }
    renderChannelList(allChannels.filter(function (ch) {
      return ch.name.toLowerCase().indexOf(q) !== -1;
    }));
  }

  subsLoad.addEventListener("click", function () {
    subsStatus.textContent = "Loading subscriptions…";
    subsList.innerHTML = "";
    subsFilter.style.display = "none";
    subsLoad.disabled = true;
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/subscriptions", true);
    xhr.timeout = 45000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      subsLoad.disabled = false;
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        subsStatus.textContent = "Failed to parse response."; return;
      }
      if (data.error) {
        subsStatus.textContent = "Error: " + data.error; return;
      }
      allChannels = data.channels || [];
      if (!allChannels.length) {
        subsStatus.textContent = "No subscriptions found."; return;
      }
      var syncedAt = data.synced_at ? " · synced " + data.synced_at.slice(0, 10) : "";
      subsStatus.textContent = allChannels.length + " channels" + syncedAt;
      subsFilter.style.display = "";
      subsFilter.value = "";
      fetchFavs(function () { renderChannelList(allChannels); });
    };
    xhr.send();
  });

  subsFilter.addEventListener("input", applyFilter);

  // ── Weather (IP-based, no geolocation API needed) ──────────────────────
  (function initWeather() {
    var WMO_ICONS = {
      0:"☀️",1:"🌤️",2:"⛅",3:"☁️",45:"🌫️",48:"🌫️",
      51:"🌦️",53:"🌦️",55:"🌧️",61:"🌧️",63:"🌧️",65:"🌧️",
      71:"🌨️",73:"🌨️",75:"❄️",80:"🌦️",81:"🌧️",82:"⛈️",
      95:"⛈️",96:"⛈️",99:"⛈️"
    };
    var WMO_DESC = {
      0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",
      45:"Fog",48:"Icy fog",51:"Light drizzle",53:"Drizzle",55:"Heavy drizzle",
      61:"Light rain",63:"Rain",65:"Heavy rain",71:"Light snow",73:"Snow",
      75:"Heavy snow",80:"Showers",81:"Rain showers",82:"Violent showers",
      95:"Thunderstorm",96:"Thunderstorm w/ hail",99:"Thunderstorm w/ heavy hail"
    };

    function showWeatherText(temp, code, city) {
      var el = document.getElementById("weather-text");
      if (!el) return;
      var icon = WMO_ICONS[code] || "🌡️";
      var desc = WMO_DESC[code] || "";
      el.textContent = icon + " " + Math.round(temp) + "°C  " + desc + (city ? "  ·  " + city : "");
    }

    function fetchWeather(lat, lon, city) {
      var xhr = new XMLHttpRequest();
      xhr.open("GET", "https://api.open-meteo.com/v1/forecast?latitude=" + lat +
               "&longitude=" + lon + "&current_weather=true&forecast_days=1", true);
      xhr.timeout = 8000;
      xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4 || xhr.status !== 200) return;
        try {
          var d = JSON.parse(xhr.responseText);
          var cw = d.current_weather;
          showWeatherText(cw.temperature, cw.weathercode, city);
        } catch(e) {}
      };
      xhr.send();
    }

    // Use IP geolocation — works over HTTP, no browser permission needed
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "https://ipapi.co/json/", true);
    xhr.timeout = 6000;
    xhr.onreadystatechange = function() {
      if (xhr.readyState !== 4 || xhr.status !== 200) return;
      try {
        var d = JSON.parse(xhr.responseText);
        if (d.latitude && d.longitude) fetchWeather(d.latitude, d.longitude, d.city || "");
      } catch(e) {}
    };
    xhr.send();
  })();

  var feedMoreWrap = document.getElementById("feed-more-wrap");
  var feedMoreBtn  = document.getElementById("feed-more");

  // ── YouTube search ──
  var ytSearchInput    = document.getElementById("yt-search-input");
  var ytSearchGoBtn    = document.getElementById("yt-search-go");
  var ytSearchStatus   = document.getElementById("yt-search-status");
  var ytSearchGrid     = document.getElementById("yt-search-grid");
  var ytSearchMoreWrap = document.getElementById("yt-search-more-wrap");
  var ytSearchMoreBtn  = document.getElementById("yt-search-more");
  var ytSearchLimit    = 12;

  function appendSearchCards(videos) {
    videos.forEach(function (v) {
      var card = document.createElement("div");
      card.className = "feed-card";
      var dur = fmtDuration(v.duration);
      card.innerHTML =
        '<img class="feed-thumb" src="' + (v.thumb || "") + '" loading="lazy" alt="">' +
        '<div class="feed-info">' +
        '<div class="feed-title">' + escHtml(v.title) + '</div>' +
        (dur ? '<div class="feed-dur">' + escHtml(dur) + '</div>' : '') +
        '</div>';
      card.addEventListener("click", function () {
        window.location.href = buildWatchUrl(v.url, feedQuality.value, feedSync.value, feedMode.value, feedProfile.value);
      });
      ytSearchGrid.appendChild(card);
    });
  }

  function runYtSearch(append) {
    var q = (ytSearchInput.value || "").trim();
    if (!q) { ytSearchInput.focus(); return; }
    if (!append) {
      ytSearchLimit = 12;
      ytSearchGrid.innerHTML = "";
      ytSearchMoreWrap.style.display = "none";
    }
    ytSearchStatus.textContent = append ? "Loading more…" : "Searching…";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/ytsearch?q=" + encodeURIComponent(q) + "&limit=" + ytSearchLimit, true);
    xhr.timeout = 30000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status < 200 || xhr.status >= 300) {
        ytSearchStatus.textContent = "Error: " + xhr.status;
        return;
      }
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        ytSearchStatus.textContent = "Failed to parse response.";
        return;
      }
      if (data.error) {
        ytSearchStatus.textContent = "Error: " + data.error;
        return;
      }
      var videos = data.videos || [];
      if (!videos.length) {
        ytSearchStatus.textContent = "No results found.";
        return;
      }
      if (append) {
        var existing = ytSearchGrid.querySelectorAll(".feed-card").length;
        appendSearchCards(videos.slice(existing));
      } else {
        appendSearchCards(videos);
      }
      ytSearchStatus.textContent = ytSearchGrid.querySelectorAll(".feed-card").length + " results";
      ytSearchMoreWrap.style.display = "block";
    };
    xhr.send();
  }

  ytSearchGoBtn.addEventListener("click", function () { runYtSearch(false); });
  ytSearchInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") runYtSearch(false);
  });
  ytSearchMoreBtn.addEventListener("click", function () {
    ytSearchLimit += 12;
    runYtSearch(true);
  });
  var feedLimit    = 12;

  function appendFeedCards(videos) {
    videos.forEach(function (v) {
      var card = document.createElement("div");
      card.className = "feed-card";
      var dur = fmtDuration(v.duration);
      card.innerHTML =
        '<img class="feed-thumb" src="' + (v.thumb || "") + '" loading="lazy" alt="">' +
        '<div class="feed-info">' +
        '<div class="feed-title">' + escHtml(v.title) + '</div>' +
        (dur ? '<div class="feed-dur">' + escHtml(dur) + '</div>' : '') +
        '</div>';
      card.addEventListener("click", function () {
        window.location.href = buildWatchUrl(v.url, feedQuality.value, feedSync.value, feedMode.value, feedProfile.value);
      });
      feedGrid.appendChild(card);
    });
  }

  function loadFeed(append) {
    var ch = (feedChannel.value || "").trim();
    if (!ch) { feedChannel.focus(); return; }
    if (!append) {
      feedLimit = 12;
      feedGrid.innerHTML = "";
      feedMoreWrap.style.display = "none";
    }
    feedStatus.textContent = "Loading…";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/feed?channel=" + encodeURIComponent(ch) + "&limit=" + feedLimit, true);
    xhr.timeout = 30000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status < 200 || xhr.status >= 300) {
        feedStatus.textContent = "Error: " + xhr.status;
        return;
      }
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        feedStatus.textContent = "Failed to parse response.";
        return;
      }
      if (data.error) {
        feedStatus.textContent = "Error: " + data.error;
        return;
      }
      var videos = data.videos || [];
      if (!videos.length) {
        feedStatus.textContent = "No videos found for that channel.";
        feedMoreWrap.style.display = "none";
        return;
      }
      if (append) {
        var existing = feedGrid.querySelectorAll(".feed-card").length;
        appendFeedCards(videos.slice(existing));
      } else {
        appendFeedCards(videos);
      }
      feedStatus.textContent = feedGrid.querySelectorAll(".feed-card").length + " videos";
      feedMoreWrap.style.display = "block";
    };
    xhr.send();
  }

  feedMoreBtn.addEventListener("click", function () {
    feedLimit += 12;
    loadFeed(true);
  });

  feedGoBtn.addEventListener("click", loadFeed);
  feedChannel.addEventListener("keydown", function (e) {
    if ((e.key || "") === "Enter" || e.keyCode === 13) loadFeed();
  });

  // ── Acestream tab ──
  var aceIdInput  = document.getElementById("ace-id");
  var aceHost     = document.getElementById("ace-host");
  var aceGo       = document.getElementById("ace-go");
  var aceSaveName = document.getElementById("ace-save-name");
  var aceSaveId   = document.getElementById("ace-save-id");
  var aceSaveBtn  = document.getElementById("ace-save-btn");
  var aceSavedList= document.getElementById("ace-saved-list");

  var aceMode = createButtonGroup("ace-mode-btns", modeOptions, defaultMode);

  var aceQuality = createButtonGroup("ace-quality-btns", qualityOptions, "auto");
  var aceProfile = createButtonGroup("ace-profile-btns", profileOptions, "auto");

  var aceSync = createButtonGroup("ace-sync-btns", [
    { value: "0", label: "0s" },
    { value: "500", label: "0.5s" },
    { value: "1000", label: "1s" },
    { value: "1500", label: "1.5s" },
    { value: "2000", label: "2s" },
    { value: "2500", label: "2.5s" },
    { value: "3000", label: "3s" },
    { value: "3500", label: "3.5s" },
    { value: "4000", label: "4s" }
  ], "{{audio_delay_ms}}");

  // Persist proxy host in localStorage; streams are stored server-side
  var ACE_HOST_KEY = "ace_proxy_host";

  aceHost.value = localStorage.getItem(ACE_HOST_KEY) || "192.168.1.7:6878";
  aceHost.addEventListener("change", function () {
    localStorage.setItem(ACE_HOST_KEY, aceHost.value.trim());
  });

  function aceContentId(raw) {
    raw = (raw || "").trim();
    // acestream://HASH → extract hash
    if (/^acestream:[/][/]/i.test(raw)) raw = raw.slice(12);
    // Full URL → extract id param
    if (/^https?:[/][/]/i.test(raw)) {
      var m = raw.match(/[?&]id=([a-f0-9]{40})/i);
      if (m) return m[1];
    }
    return raw;
  }

  function buildAceUrl(raw) {
    var cid = aceContentId(raw);
    if (!cid) return null;
    var host = (aceHost.value || "").trim() || "192.168.1.7:6878";
    return "http://" + host + "/ace/getstream?id=" + cid;
  }

  function openAceStream() {
    var raw = (aceIdInput.value || "").trim();
    if (!raw) { aceIdInput.focus(); return; }
    var url = buildAceUrl(raw);
    if (!url) { aceIdInput.focus(); return; }
    localStorage.setItem(ACE_HOST_KEY, (aceHost.value || "").trim());
    window.location.href = buildWatchUrl(url, aceQuality.value, aceSync.value, aceMode.value, aceProfile.value);
  }

  aceGo.addEventListener("click", openAceStream);
  aceIdInput.addEventListener("keydown", function (e) {
    if ((e.key || "") === "Enter" || e.keyCode === 13) openAceStream();
  });

  // Saved streams (server-side)
  function renderSaved(list) {
    aceSavedList.innerHTML = "";
    if (!list || !list.length) {
      aceSavedList.innerHTML = '<p class="empty">No saved streams yet.</p>';
      return;
    }
    list.forEach(function (item, idx) {
      var row = document.createElement("div");
      row.className = "stream-row";
      row.innerHTML =
        '<span style="cursor:pointer;flex:1;" data-idx="' + idx + '">' +
        escHtml(item.name) + '</span>' +
        '<span style="font-family:monospace;font-size:.75rem;color:var(--muted);margin-right:12px;">' +
        escHtml(item.id.slice(0, 12)) + '…</span>' +
        '<button data-del="' + idx + '" style="background:transparent;border:1px solid var(--border);' +
        'color:var(--muted);border-radius:4px;padding:2px 8px;cursor:pointer;font-size:.75rem;">✕</button>';
      row.querySelector("[data-idx]").addEventListener("click", function () {
        var url = buildAceUrl(item.id);
        if (url) window.location.href = buildWatchUrl(url, aceQuality.value, aceSync.value, aceMode.value, aceProfile.value);
      });
      row.querySelector("[data-del]").addEventListener("click", function (e) {
        e.stopPropagation();
        var xhr = new XMLHttpRequest();
        xhr.open("DELETE", "/ace_streams?idx=" + idx, true);
        xhr.onload = function () {
          try { renderSaved(JSON.parse(xhr.responseText).streams); } catch(ex) {}
        };
        xhr.send();
      });
      aceSavedList.appendChild(row);
    });
  }

  function fetchSaved() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/ace_streams", true);
    xhr.onload = function () {
      try { renderSaved(JSON.parse(xhr.responseText).streams); } catch(ex) {}
    };
    xhr.send();
  }

  aceSaveBtn.addEventListener("click", function () {
    var name = (aceSaveName.value || "").trim();
    var raw  = (aceSaveId.value  || "").trim();
    if (!name || !raw) return;
    var cid = aceContentId(raw);
    if (!cid) return;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/ace_streams", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onload = function () {
      try { renderSaved(JSON.parse(xhr.responseText).streams); } catch(ex) {}
    };
    aceSaveName.value = "";
    aceSaveId.value   = "";
    xhr.send(JSON.stringify({name: name, id: cid}));
  });

  fetchSaved();

  // ── Local Media tab ──
  var localRefresh = document.getElementById("local-refresh");
  var localStatus  = document.getElementById("local-status");
  var localList    = document.getElementById("local-list");

  var localMode = createButtonGroup("local-mode-btns", modeOptions, defaultMode);
  var localProfile = createButtonGroup("local-profile-btns", profileOptions, "auto");

  var localSync = createButtonGroup("local-sync-btns", [
    { value: "0", label: "0s" },
    { value: "500", label: "0.5s" },
    { value: "1000", label: "1s" },
    { value: "1500", label: "1.5s" },
    { value: "2000", label: "2s" },
    { value: "2500", label: "2.5s" },
    { value: "3000", label: "3s" },
    { value: "3500", label: "3.5s" },
    { value: "4000", label: "4s" }
  ], "{{local_media_video_delay_ms}}");

  var localCurrentDir = "";

  function renderLocalBrowser(data) {
    localList.innerHTML = "";
    var folders = data.folders || [];
    var files = data.files || [];
    var currentDir = data.current_dir || "";

    // Breadcrumb
    var crumb = document.createElement("div");
    crumb.style.cssText = "font-size:.8rem;color:var(--muted);margin-bottom:8px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;";
    var parts = currentDir ? currentDir.split("/") : [];
    var rootSpan = document.createElement("span");
    rootSpan.textContent = "\\uD83D\\uDCC1 /";
    rootSpan.style.cssText = "cursor:pointer;color:var(--accent);";
    rootSpan.addEventListener("click", function () { loadLocalDir(""); });
    crumb.appendChild(rootSpan);
    parts.forEach(function (part, i) {
      var sep = document.createElement("span");
      sep.textContent = " / ";
      crumb.appendChild(sep);
      var sp = document.createElement("span");
      sp.textContent = part;
      var dirPath = parts.slice(0, i + 1).join("/");
      if (i < parts.length - 1) {
        sp.style.cssText = "cursor:pointer;color:var(--accent);";
        sp.addEventListener("click", (function(d){ return function(){ loadLocalDir(d); }; })(dirPath));
      } else {
        sp.style.color = "var(--text)";
      }
      crumb.appendChild(sp);
    });
    localList.appendChild(crumb);

    if (!folders.length && !files.length) {
      var empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No video files or subfolders here.";
      localList.appendChild(empty);
      return;
    }

    // Folders
    folders.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "stream-row";
      row.style.cursor = "pointer";
      row.innerHTML =
        '<span style="font-size:.95rem;">\\uD83D\\uDCC2 ' + escHtml(item.name) + '</span>' +
        '<span style="font-family:monospace;font-size:.75rem;color:var(--muted);">OPEN \u2192</span>';
      row.addEventListener("click", function () { loadLocalDir(item.path); });
      localList.appendChild(row);
    });

    // Files
    files.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "stream-row";
      row.style.cursor = "pointer";
      row.innerHTML =
        '<span style="font-size:.95rem;">\\uD83C\\uDFA5 ' + escHtml(item.name) + '</span>' +
        '<span style="font-family:monospace;font-size:.75rem;color:var(--muted);">PLAY \u2192</span>';
      row.addEventListener("click", function () {
        var localUrl = "/local_watch?file=" + encodeURIComponent(item.path) +
          "&sync=" + encodeURIComponent(localSync.value);
        if (localMode.value) localUrl += "&mode=" + encodeURIComponent(localMode.value);
        if (localProfile.value) localUrl += "&profile=" + encodeURIComponent(localProfile.value);
        window.location.href = localUrl;
      });
      localList.appendChild(row);
    });
  }

  function loadLocalDir(dir) {
    localCurrentDir = dir || "";
    localStatus.textContent = "Loading…";
    localList.innerHTML = "";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/local_media" + (dir ? "?dir=" + encodeURIComponent(dir) : ""), true);
    xhr.timeout = 10000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) {
        localStatus.textContent = "Failed to parse response."; return;
      }
      if (data.error) { localStatus.textContent = "Error: " + data.error; return; }
      var total = (data.folders || []).length + (data.files || []).length;
      localStatus.textContent = total + " item" + (total !== 1 ? "s" : "");
      renderLocalBrowser(data);
    };
    xhr.send();
  }

  localRefresh.addEventListener("click", function () { loadLocalDir(localCurrentDir); });
  var localOpened = false;
  document.querySelector('[data-tab="local"]').addEventListener("click", function () {
    if (localOpened) return;
    localOpened = true;
    loadLocalDir("");
  });
  } catch(e) { /* init error — non-fatal */ }
})();
</script>
</body></html>"""

WATCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCarStream Watch</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Rajdhani:wght@300;500&display=swap');
  :root{--red:#e31937;--dark:#090909;--panel:#111117;--border:#252530;--text:#e0e0ee;}
  @media(prefers-color-scheme:light){:root{--dark:#f4f4f6;--panel:#ffffff;--border:#d8d8e0;--text:#1a1a2e;}}
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:var(--dark);color:var(--text);font-family:'Rajdhani',sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:16px;}
  .top{width:100%;max-width:1280px;display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:12px;flex-wrap:wrap;}
  .title{font-family:'Orbitron',monospace;letter-spacing:.1em;color:var(--red);font-size:1rem;}
  .back{color:var(--red);text-decoration:none;font-family:monospace;}
  .wrap{width:100%;max-width:1280px;background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:10px;}
  img{width:100%;height:auto;display:block;background:black;border-radius:8px;}
  audio{width:100%;margin-top:10px;}
  .diag{margin-top:10px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-family:monospace;font-size:.85rem;line-height:1.4;white-space:pre-wrap;color:#f0b5bf;background:#160d11;display:none;}
  .seek-bar{display:flex;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap;}
  .seek-btn{background:var(--panel);border:1px solid var(--border);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:1rem;font-weight:500;padding:6px 14px;border-radius:6px;cursor:pointer;transition:border-color .15s,color .15s;}
  .seek-btn:hover{border-color:var(--red);color:var(--red);}
  .seek-btn.active{border-color:var(--red);color:var(--red);}
  .seek-pending{font-family:monospace;font-size:.9rem;color:var(--red);min-width:80px;}
  .seek-cancel{background:none;border:none;color:#888;font-size:.8rem;cursor:pointer;text-decoration:underline;padding:0;}
  .elapsed{font-family:monospace;font-size:1rem;color:var(--text);margin-left:auto;letter-spacing:.05em;}
  .live-badge{font-family:'Orbitron',monospace;font-size:.65rem;letter-spacing:.12em;color:#fff;background:var(--red);padding:2px 7px;border-radius:3px;text-transform:uppercase;margin-left:auto;display:none;}
  .resume-banner{margin-top:10px;padding:10px 14px;background:#1a1200;border:1px solid #6b4f00;border-radius:6px;font-size:.9rem;display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
  .resume-banner a{color:#f5c518;font-weight:600;cursor:pointer;text-decoration:underline;}
  .resume-banner .dismiss{color:#888;font-size:.8rem;cursor:pointer;text-decoration:underline;background:none;border:none;}
  .stream-title{font-size:.95rem;color:var(--text);font-family:'Rajdhani',sans-serif;font-weight:500;padding:8px 4px 2px;letter-spacing:.02em;min-height:1.4em;}
  .sync-bar{display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap;padding:8px 4px;border-top:1px solid var(--border);}
  .sync-label{font-family:'Orbitron',monospace;font-size:.65rem;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;}
  .sync-btn{background:var(--panel);border:1px solid var(--border);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:1rem;font-weight:500;padding:6px 14px;border-radius:6px;cursor:pointer;}
  .sync-btn:hover{border-color:var(--red);color:var(--red);}
  .sync-val{font-family:monospace;font-size:.95rem;color:var(--red);min-width:60px;text-align:center;}
</style>
</head>
<body>
  <div class="top">
    <div class="title">MJPEG + AUDIO</div>
    <a class="back" href="/">← Back</a>
  </div>
  <div class="wrap">
    <img id="mjpeg" alt="Live MJPEG stream">
    <div id="stream-title" class="stream-title"></div>
    <audio id="audio" controls autoplay playsinline></audio>
    <div class="sync-bar">
      <span class="sync-label">Audio delay</span>
      <button class="sync-btn" data-delta="-0.5">−0.5s</button>
      <button class="sync-btn" data-delta="-0.1">−0.1s</button>
      <span id="sync-val" class="sync-val">0.0s</span>
      <button class="sync-btn" data-delta="0.1">+0.1s</button>
      <button class="sync-btn" data-delta="0.5">+0.5s</button>
    </div>
    <div class="seek-bar">
      <span class="sync-label" style="margin-right:4px;">Video</span>
      <button class="seek-btn" data-mins="-10">-10 min</button>
      <button class="seek-btn" data-mins="1">+1 min</button>
      <button class="seek-btn" data-mins="5">+5 min</button>
      <button class="seek-btn" data-mins="10">+10 min</button>
      <span id="seek-pending" class="seek-pending"></span>
      <button id="seek-cancel" class="seek-cancel" style="display:none">cancel</button>
      <span id="live-badge" class="live-badge">● Live</span>
      <span id="elapsed" class="elapsed">0:00:00</span>
    </div>
    <div id="resume-banner" class="resume-banner" style="display:none">
      <span id="resume-text"></span>
      <a id="resume-yes">Resume</a>
      <button class="dismiss" id="resume-no">dismiss</button>
    </div>
    <div id="diag" class="diag"></div>
  </div>
<script>
(function () {
  var sid = "{{stream_id}}";
  var syncMs = "{{sync_ms}}";
  var videoUrl = "{{video_url}}";
  var videoQuality = "{{video_quality}}";
  var localFile = "{{local_file}}";
  if (!sid) {
    window.location.href = "/";
    return;
  }
  var q = "?sid=" + encodeURIComponent(sid) + "&sync=" + encodeURIComponent(syncMs);
  var img = document.getElementById("mjpeg");
  var audio = document.getElementById("audio");
  var diag = document.getElementById("diag");
  var seekPending  = document.getElementById("seek-pending");
  var seekCancel   = document.getElementById("seek-cancel");
  var elapsedEl    = document.getElementById("elapsed");
  var liveBadgeEl  = document.getElementById("live-badge");
  var resumeBanner = document.getElementById("resume-banner");
  var resumeText   = document.getElementById("resume-text");
  var resumeYes    = document.getElementById("resume-yes");
  var resumeNo     = document.getElementById("resume-no");

  // Start audio first so its pipeline is already running and buffered.
  audio.src = "/audio?sid=" + encodeURIComponent(sid);
  audio.preload = "auto";
  audio.muted = false;
  audio.volume = 1.0;
  try {
    var p = audio.play();
    if (p && typeof p.catch === "function") p.catch(function () {});
  } catch (e) {}

  // Some browsers (including embedded WebViews) may block autoplay without
  // interaction. Retry on first user gesture.
  var retryPlay = function () {
    try {
      var p2 = audio.play();
      if (p2 && typeof p2.catch === "function") p2.catch(function () {});
    } catch (e) {}
    window.removeEventListener("click", retryPlay, true);
    window.removeEventListener("touchstart", retryPlay, true);
    window.removeEventListener("keydown", retryPlay, true);
  };
  window.addEventListener("click", retryPlay, true);
  window.addEventListener("touchstart", retryPlay, true);
  window.addEventListener("keydown", retryPlay, true);

  audio.addEventListener("loadedmetadata", function () {
    if (!isFinite(audio.duration)) {
      if (liveBadgeEl) liveBadgeEl.style.display = "inline-block";
      if (elapsedEl)   elapsedEl.style.display    = "none";
    }
  });

  // ── Real-time audio delay control ───────────────────────────────────────
  var syncValEl   = document.getElementById("sync-val");
  // Start display at the server-configured initial delay
  var audioDelayS = parseFloat(syncMs) / 1000 || 0;
  var pauseTimer  = null;

  function updateSyncDisplay() {
    syncValEl.textContent = (audioDelayS >= 0 ? "+" : "") + audioDelayS.toFixed(1) + "s";
  }
  updateSyncDisplay();

  function resumeAudio() {
    if (audio.paused) {
      try { var p = audio.play(); if (p && p.catch) p.catch(function(){}); } catch(e) {}
    }
  }

  var rateTimer = null;
  function applyAudioDelta(deltaS) {
    clearTimeout(pauseTimer);
    clearTimeout(rateTimer);
    audio.playbackRate = 1.0;
    audioDelayS = Math.round((audioDelayS + deltaS) * 10) / 10;
    updateSyncDisplay();
    var isLive = !isFinite(audio.duration);
    if (deltaS > 0) {
      // Audio plays later → pause for deltaS then resume
      audio.pause();
      pauseTimer = setTimeout(resumeAudio, Math.round(deltaS * 1000));
    } else {
      // Audio plays earlier
      if (!isLive) {
        // VOD: skip the audio forward
        audio.currentTime = Math.max(0, audio.currentTime + (-deltaS));
        resumeAudio();
      } else {
        // Live: can't seek, so play at 2x for |deltaS| seconds. That
        // advances audio by |deltaS| seconds of real-time content,
        // undoing prior positive offsets (and going negative further).
        resumeAudio();
        audio.playbackRate = 2.0;
        rateTimer = setTimeout(function () {
          audio.playbackRate = 1.0;
        }, Math.round((-deltaS) * 1000));
      }
    }
  }

  document.querySelectorAll(".sync-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      applyAudioDelta(parseFloat(btn.getAttribute("data-delta")));
    });
  });

  // Always request video immediately; server-side frame buffering applies
  // sync_ms without skipping content from the beginning.
  img.src = "/stream" + q;

  function showDiag(message) {
    diag.style.display = "block";
    diag.textContent = message;
  }

  img.addEventListener("error", function () {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/stream_status?sid=" + encodeURIComponent(sid), true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status < 200 || xhr.status >= 300) {
        showDiag("Video stream failed to load and diagnostics request failed.");
        return;
      }
      try {
        var data = JSON.parse(xhr.responseText);
        var msg = [
          "Video stream failed to load.",
          "status: " + (data.status || "unknown"),
          "error: " + (data.error || "n/a"),
          "detail: " + (data.error_detail || "n/a")
        ].join("\\n");
        showDiag(msg);
      } catch (err) {
        showDiag("Video stream failed to load and diagnostics parse failed.");
      }
    };
    xhr.send();
  });

  // ── Seek controls ────────────────────────────────────────────────────────
  // Read seek offset already applied (so accumulated offset stays correct
  // if the user seeks multiple times).
  var params = new URLSearchParams(window.location.search);
  var baseSeekS = parseInt("{{seek_s}}", 10) || parseInt(params.get("seek") || "0", 10) || 0;
  var pendingOffsetS = 0;
  var seekTimer = null;
  var countdownInterval = null;
  var SEEK_DEBOUNCE_MS = 3000;

  function fmtOffset(s) {
    var m = Math.floor(s / 60);
    var sec = s % 60;
    return "+" + m + "m" + (sec ? sec + "s" : "");
  }

  function startSeekTimer() {
    clearTimeout(seekTimer);
    clearInterval(countdownInterval);
    var countdown = SEEK_DEBOUNCE_MS / 1000;
    seekPending.textContent = fmtOffset(pendingOffsetS) + " (seeking in " + countdown + "s)";
    seekCancel.style.display = "inline";

    countdownInterval = setInterval(function () {
      countdown--;
      if (countdown > 0) {
        seekPending.textContent = fmtOffset(pendingOffsetS) + " (seeking in " + countdown + "s)";
      }
    }, 1000);

    seekTimer = setTimeout(function () {
      clearInterval(countdownInterval);
      var targetSeek = Math.max(0, baseSeekS + pendingOffsetS);
      seekPending.textContent = "Reloading\u2026";
      seekCancel.style.display = "none";
      var watchUrl;
      if (localFile) {
        watchUrl = "/local_watch?file=" + encodeURIComponent(localFile) + "&seek=" + targetSeek;
        if (syncMs && syncMs !== "0") watchUrl += "&sync=" + encodeURIComponent(syncMs);
      } else {
        watchUrl = "/watch?url=" + encodeURIComponent(videoUrl) + "&seek=" + targetSeek;
        if (videoQuality) watchUrl += "&quality=" + encodeURIComponent(videoQuality);
        if (syncMs && syncMs !== "0") watchUrl += "&sync=" + encodeURIComponent(syncMs);
      }
      window.location.href = watchUrl;
    }, SEEK_DEBOUNCE_MS);
  }

  if (videoUrl || localFile) {
    document.querySelectorAll(".seek-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        pendingOffsetS = Math.max(-baseSeekS, pendingOffsetS + parseInt(btn.getAttribute("data-mins"), 10) * 60);
        startSeekTimer();
      });
    });

    seekCancel.addEventListener("click", function () {
      clearTimeout(seekTimer);
      clearInterval(countdownInterval);
      pendingOffsetS = 0;
      seekPending.textContent = "";
      seekCancel.style.display = "none";
    });
  } else {
    // Seek not available (e.g. direct stream)
    document.querySelector(".seek-bar").style.display = "none";
    elapsedEl.style.display = "none";
  }

  // Fetch fps + title from server once the stream is live
  var titleEl = document.getElementById("stream-title");
  (function pollStatus() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/stream_status?sid=" + encodeURIComponent(sid), true);
    xhr.timeout = 3000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      try {
        var d = JSON.parse(xhr.responseText);
        if (d.title && titleEl.textContent !== d.title) titleEl.textContent = d.title;
        if (!d.title) setTimeout(pollStatus, 2000);
      } catch(e) {
        setTimeout(pollStatus, 2000);
      }
    };
    xhr.send();
  })();

  // ── Elapsed time display ────────────────────────────────────────────────
  var pageStartMs = Date.now();

  function currentElapsedS() {
    return baseSeekS + Math.floor((Date.now() - pageStartMs) / 1000);
  }

  function fmtElapsed(s) {
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    return h + ":" + (m < 10 ? "0" : "") + m + ":" + (sec < 10 ? "0" : "") + sec;
  }

  if (videoUrl || localFile) {
    setInterval(function () {
      elapsedEl.textContent = fmtElapsed(currentElapsedS());
    }, 1000);
  }

  // ── Progress save / resume ──────────────────────────────────────────────
  var progressKey = videoUrl || localFile;

  function buildResumeUrl(posS) {
    if (localFile) {
      var u = "/local_watch?file=" + encodeURIComponent(localFile) + "&seek=" + posS;
      if (syncMs && syncMs !== "0") u += "&sync=" + encodeURIComponent(syncMs);
      return u;
    }
    var u = "/watch?url=" + encodeURIComponent(videoUrl) + "&seek=" + posS;
    if (videoQuality) u += "&quality=" + encodeURIComponent(videoQuality);
    if (syncMs && syncMs !== "0") u += "&sync=" + encodeURIComponent(syncMs);
    return u;
  }

  function saveProgress(posS) {
    if (!progressKey || posS < 10) return;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/progress", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.send(JSON.stringify({url: progressKey, pos_s: posS}));
  }

  function clearProgress() {
    if (!progressKey) return;
    var xhr = new XMLHttpRequest();
    xhr.open("DELETE", "/progress?url=" + encodeURIComponent(progressKey), true);
    xhr.send();
  }

  // Save every 30 seconds
  if (progressKey) {
    setInterval(function () { saveProgress(currentElapsedS()); }, 30000);
  }

  // Check for saved position on load — offer resume if > 60s into the video
  // and we're not already starting from a seek position
  if (progressKey && baseSeekS === 0) {
    var chkXhr = new XMLHttpRequest();
    chkXhr.open("GET", "/progress?url=" + encodeURIComponent(progressKey), true);
    chkXhr.timeout = 3000;
    chkXhr.onreadystatechange = function () {
      if (chkXhr.readyState !== 4) return;
      try {
        var saved = JSON.parse(chkXhr.responseText);
        var posS = saved.pos_s || 0;
        var savedAt = saved.saved_at || 0;
        var ageH = (Date.now() / 1000 - savedAt) / 3600;
        // Only offer resume if position is > 1 min and saved within 48 h
        if (posS > 60 && ageH < 48) {
          resumeText.textContent = "Resume from " + fmtElapsed(posS) + "?";
          resumeYes.href = buildResumeUrl(posS);
          resumeYes.addEventListener("click", function () { clearProgress(); });
          resumeBanner.style.display = "flex";
        }
      } catch(e) {}
    };
    chkXhr.send();
  }

  resumeNo.addEventListener("click", function () {
    resumeBanner.style.display = "none";
  });

  // On stream error, add position hint to the diagnostics message
  var origError = img.onerror;
  img.addEventListener("error", function () {
    var posS = currentElapsedS();
    if (posS > 10) {
      saveProgress(posS);
      // Append resume link below the existing diag after a short delay
      // (let the existing error handler run first)
      setTimeout(function () {
        if (diag.style.display !== "none" && progressKey) {
          diag.textContent += "\\n\\nLast saved position: " + fmtElapsed(posS) +
            "\\nReload from here: " + window.location.origin + buildResumeUrl(posS);
        }
      }, 500);
    }
  });
})();
</script>
</body></html>"""


AUDIO_WATCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCarStream — Audio</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Rajdhani:wght@300;500&display=swap');
  :root{--red:#e31937;--dark:#090909;--panel:#111117;--border:#252530;--text:#e0e0ee;--muted:#555568;}
  @media(prefers-color-scheme:light){:root{--dark:#f4f4f6;--panel:#ffffff;--border:#d8d8e0;--text:#1a1a2e;--muted:#888899;}}
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:var(--dark);color:var(--text);font-family:'Rajdhani',sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:16px;}
  .top{width:100%;max-width:720px;display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;gap:12px;}
  .title{font-family:'Orbitron',monospace;letter-spacing:.1em;color:var(--red);font-size:1rem;}
  .back{color:var(--red);text-decoration:none;font-family:monospace;}
  .wrap{width:100%;max-width:720px;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:28px 24px;display:flex;flex-direction:column;gap:14px;}
  audio{width:100%;}
  .stream-title{font-size:1rem;color:var(--text);font-family:'Rajdhani',sans-serif;font-weight:500;letter-spacing:.02em;min-height:1.4em;}
  .diag{padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-family:monospace;font-size:.85rem;line-height:1.4;white-space:pre-wrap;color:#f0b5bf;background:#160d11;display:none;}
  .status{font-family:'Orbitron',monospace;font-size:.7rem;letter-spacing:.1em;color:var(--red);text-transform:uppercase;}
  .seek-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-top:10px;border-top:1px solid var(--border);}
  .seek-btn{background:var(--panel);border:1px solid var(--border);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:.95rem;font-weight:500;padding:6px 12px;border-radius:6px;cursor:pointer;}
  .seek-btn:hover{border-color:var(--red);color:var(--red);}
  .elapsed{font-family:monospace;font-size:1rem;color:var(--text);margin-left:auto;letter-spacing:.05em;}
  .live-badge{font-family:'Orbitron',monospace;font-size:.65rem;letter-spacing:.12em;color:#fff;background:var(--red);padding:2px 7px;border-radius:3px;margin-left:auto;display:none;}
  .seek-label{font-family:'Orbitron',monospace;font-size:.65rem;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;}
  .seek-pending{font-family:monospace;font-size:.85rem;color:var(--red);}
  .seek-cancel{background:none;border:none;color:#888;font-size:.8rem;cursor:pointer;text-decoration:underline;padding:0;}
</style>
</head>
<body>
  <div class="top">
    <div class="title">AUDIO STREAM</div>
    <a class="back" href="/">← Back</a>
  </div>
  <div class="wrap">
    <div id="stream-title" class="stream-title"></div>
    <div id="status-msg" class="status">Connecting…</div>
    <audio id="audio" controls autoplay playsinline></audio>
    <div class="seek-bar" id="seek-bar">
      <span class="seek-label">Seek</span>
      <button class="seek-btn" data-mins="-10">-10 min</button>
      <button class="seek-btn" data-mins="1">+1 min</button>
      <button class="seek-btn" data-mins="5">+5 min</button>
      <button class="seek-btn" data-mins="10">+10 min</button>
      <span id="seek-pending" class="seek-pending"></span>
      <button id="seek-cancel" class="seek-cancel" style="display:none">cancel</button>
      <span id="live-badge" class="live-badge">● Live</span>
      <span id="elapsed" class="elapsed">0:00:00</span>
    </div>
    <div id="diag" class="diag"></div>
  </div>
<script>
(function () {
  var sid        = "{{stream_id}}";
  var syncMs     = "{{sync_ms}}";
  var videoUrl   = "{{video_url}}";
  var seekS      = parseInt("{{seek_s}}", 10) || 0;
  var durationS  = parseInt("{{duration_s}}", 10) || 0;  // 0 = unknown/live
  if (!sid) { window.location.href = "/"; return; }

  var audio      = document.getElementById("audio");
  var titleEl    = document.getElementById("stream-title");
  var statusEl   = document.getElementById("status-msg");
  var diagEl     = document.getElementById("diag");
  var elapsedEl  = document.getElementById("elapsed");
  var liveBadge  = document.getElementById("live-badge");
  var seekBar    = document.getElementById("seek-bar");
  var seekPend   = document.getElementById("seek-pending");
  var seekCancel = document.getElementById("seek-cancel");

  audio.src = "/audio?sid=" + encodeURIComponent(sid) + "&sync=" + encodeURIComponent(syncMs);
  audio.preload = "auto";
  try { var p = audio.play(); if (p && p.catch) p.catch(function(){}); } catch(e) {}

  var retryPlay = function () {
    try { var p2 = audio.play(); if (p2 && p2.catch) p2.catch(function(){}); } catch(e) {}
    window.removeEventListener("click", retryPlay, true);
    window.removeEventListener("touchstart", retryPlay, true);
  };
  window.addEventListener("click", retryPlay, true);
  window.addEventListener("touchstart", retryPlay, true);

  audio.addEventListener("playing", function () { statusEl.textContent = "Playing"; });
  audio.addEventListener("waiting", function () { statusEl.textContent = "Buffering…"; });
  audio.addEventListener("loadedmetadata", function () {
    // audio.duration is always Infinity for piped MP3 streams; use durationS
    // (fetched via yt-dlp) to distinguish live streams from VODs.
    var isLiveStream = !isFinite(audio.duration) && durationS === 0;
    if (isLiveStream) {
      liveBadge.style.display = "inline-block";
      elapsedEl.style.display = "none";
      seekBar.style.display   = videoUrl ? "" : "none";  // hide seek for live without url
    }
  });
  audio.addEventListener("error", function () {
    statusEl.textContent = "Error loading audio";
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/stream_status?sid=" + encodeURIComponent(sid), true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      try {
        var d = JSON.parse(xhr.responseText);
        diagEl.style.display = "block";
        diagEl.textContent = "status: " + d.status + "\\nerror: " + (d.error || "n/a") + "\\ndetail: " + (d.error_detail || "n/a");
      } catch(e) {}
    };
    xhr.send();
  });

  // ── Elapsed time ─────────────────────────────────────────────────────────
  var pageStartMs = Date.now();
  function currentElapsedS() { return seekS + Math.floor((Date.now() - pageStartMs) / 1000); }
  function fmtTime(s) {
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h + ":" + (m < 10 ? "0" : "") + m + ":" + (sec < 10 ? "0" : "") + sec;
  }
  setInterval(function () { elapsedEl.textContent = fmtTime(currentElapsedS()); }, 1000);

  // ── Seek controls (VOD only) ──────────────────────────────────────────────
  var pendingOffsetS = 0;
  var seekTimer = null, countdownInterval = null;
  var SEEK_DEBOUNCE_MS = 3000;

  if (videoUrl) {
    document.querySelectorAll(".seek-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        pendingOffsetS = Math.max(-seekS, pendingOffsetS + parseInt(btn.getAttribute("data-mins"), 10) * 60);
        startSeekTimer();
      });
    });
    seekCancel.addEventListener("click", function () {
      clearTimeout(seekTimer); clearInterval(countdownInterval);
      pendingOffsetS = 0; seekPend.textContent = ""; seekCancel.style.display = "none";
    });
  } else {
    seekBar.style.display = "none";
  }

  function startSeekTimer() {
    clearTimeout(seekTimer); clearInterval(countdownInterval);
    var countdown = SEEK_DEBOUNCE_MS / 1000;
    var sign = pendingOffsetS >= 0 ? "+" : "";
    seekPend.textContent = sign + Math.floor(pendingOffsetS / 60) + "m (seeking in " + countdown + "s)";
    seekCancel.style.display = "inline";
    countdownInterval = setInterval(function () {
      countdown--;
      if (countdown > 0) {
        var s2 = pendingOffsetS >= 0 ? "+" : "";
        seekPend.textContent = s2 + Math.floor(pendingOffsetS / 60) + "m (seeking in " + countdown + "s)";
      }
    }, 1000);
    seekTimer = setTimeout(function () {
      clearInterval(countdownInterval);
      var target = Math.max(0, seekS + pendingOffsetS);
      window.location.href = "/watch?url=" + encodeURIComponent(videoUrl) +
        "&mode=audio&seek=" + target +
        (syncMs && syncMs !== "0" ? "&sync=" + encodeURIComponent(syncMs) : "");
    }, SEEK_DEBOUNCE_MS);
  }

  // ── Title poll ────────────────────────────────────────────────────────────
  (function pollTitle() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/stream_status?sid=" + encodeURIComponent(sid), true);
    xhr.timeout = 3000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      try {
        var d = JSON.parse(xhr.responseText);
        if (d.title) titleEl.textContent = d.title;
        if (!d.title) setTimeout(pollTitle, 2000);
      } catch(e) { setTimeout(pollTitle, 2000); }
    };
    xhr.send();
  })();
})();
</script>
</body></html>"""


MP4_WATCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCarStream — MP4</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Rajdhani:wght@300;500&display=swap');
  :root{--red:#e31937;--dark:#090909;--panel:#111117;--border:#252530;--text:#e0e0ee;}
  @media(prefers-color-scheme:light){:root{--dark:#f4f4f6;--panel:#ffffff;--border:#d8d8e0;--text:#1a1a2e;}}
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:var(--dark);color:var(--text);font-family:'Rajdhani',sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:16px;}
  .top{width:100%;max-width:1280px;display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:12px;}
  .title{font-family:'Orbitron',monospace;letter-spacing:.1em;color:var(--red);font-size:1rem;}
  .back{color:var(--red);text-decoration:none;font-family:monospace;}
  .wrap{width:100%;max-width:1280px;background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:10px;}
  video{width:100%;height:auto;display:block;background:black;border-radius:8px;}
  .stream-title{font-size:.95rem;color:var(--text);font-family:'Rajdhani',sans-serif;font-weight:500;padding:8px 4px 2px;letter-spacing:.02em;min-height:1.4em;}
  .err{margin-top:10px;padding:12px 16px;background:#160d11;border:1px solid var(--red);border-radius:8px;font-family:monospace;font-size:.9rem;color:#f0b5bf;display:none;}
</style>
</head>
<body>
  <div class="top">
    <div class="title">MP4 STREAM</div>
    <a class="back" href="/">← Back</a>
  </div>
  <div class="wrap">
    <video id="video" controls autoplay playsinline>
      Your browser does not support HTML5 video.
    </video>
    <div id="stream-title" class="stream-title">{{stream_title}}</div>
    <div id="err" class="err">{{error_msg}}</div>
  </div>
<script>
(function () {
  var vid = document.getElementById("video");
  var errEl = document.getElementById("err");
  var errMsg = "{{error_msg}}";
  if (errMsg) { errEl.style.display = "block"; vid.style.display = "none"; return; }

  var directUrl = "{{direct_url}}";

  if (directUrl.indexOf("/stream_fmp4") !== -1) {
    if (!window.MediaSource) {
      errEl.style.display = "block";
      errEl.textContent = "Your browser does not support MediaSource Extensions.";
      return;
    }

    var mediaSource = new MediaSource();
    vid.src = URL.createObjectURL(mediaSource);

    mediaSource.addEventListener("sourceopen", function () {
      var mimeType = 'video/mp4; codecs="avc1.4D401E, mp4a.40.2"';
      if (!MediaSource.isTypeSupported(mimeType)) {
        mimeType = 'video/mp4; codecs="avc1.42e01e, mp4a.40.2"';
      }

      var sourceBuffer = mediaSource.addSourceBuffer(mimeType);
      var queue = [];

      function pushNext() {
        if (queue.length > 0 && !sourceBuffer.updating) {
          sourceBuffer.appendBuffer(queue.shift());
        }
      }

      sourceBuffer.addEventListener("updateend", pushNext);

      fetch(directUrl)
        .then(function (response) {
          if (!response.ok) {
            throw new Error("HTTP error " + response.status);
          }
          var reader = response.body.getReader();
          function readChunk() {
            reader.read().then(function (result) {
              if (result.done) {
                if (mediaSource.readyState === "open") {
                  mediaSource.endOfStream();
                }
                return;
              }
              queue.push(result.value);
              pushNext();
              readChunk();
            }).catch(function (e) {
              console.error("Reader error:", e);
            });
          }
          readChunk();
        })
        .catch(function (err) {
          errEl.style.display = "block";
          errEl.textContent = "Playback failed: " + err.message;
        });
    });
  } else {
    var source = document.createElement("source");
    source.src = directUrl;
    source.type = "video/mp4";
    vid.appendChild(source);

    vid.addEventListener("error", function () {
      errEl.style.display = "block";
      errEl.textContent = "Video failed to load. The direct URL may have expired — go back and try again.";
    });
    try { var p = vid.play(); if (p && p.catch) p.catch(function(){}); } catch(e) {}
  }
})();
</script>
</body></html>"""


OGV_WATCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCarStream - OGV</title>
<script src="/ogv-dist/ogv.js"></script>
<style>
  :root{--red:#e31937;--dark:#050505;--panel:#101015;--text:#f1f1f4;--muted:#8e8e9a;--line:#2a2a34;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--dark);color:var(--text);font-family:Arial,sans-serif;min-height:100vh;overflow:hidden;}
  .stage{position:fixed;inset:0;background:#000;display:flex;align-items:center;justify-content:center;}
  #player{width:100%;height:100%;display:block;background:#000;}
  .top,.controls{position:fixed;left:0;right:0;z-index:10;transition:opacity .18s;}
  .top{top:0;padding:14px 18px;background:linear-gradient(to bottom,rgba(0,0,0,.82),rgba(0,0,0,0));display:flex;align-items:center;gap:14px;}
  .back{color:#fff;text-decoration:none;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.18);border-radius:7px;padding:10px 13px;font-size:16px;}
  .title{font-weight:700;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 1px 2px #000;}
  .center{position:fixed;inset:0;z-index:9;display:flex;align-items:center;justify-content:center;gap:28px;pointer-events:none;}
  .bigbtn,.ctlbtn{border:0;color:#fff;background:rgba(255,255,255,.16);backdrop-filter:blur(8px);cursor:pointer;}
  .bigbtn{width:76px;height:76px;border-radius:50%;font-size:28px;pointer-events:auto;}
  .skip{width:60px;height:60px;border-radius:50%;font-size:16px;font-weight:700;}
  .controls{bottom:0;padding:18px;background:linear-gradient(to top,rgba(0,0,0,.86),rgba(0,0,0,0));display:flex;align-items:center;gap:12px;}
  .ctlbtn{min-width:48px;height:44px;border-radius:7px;font-size:16px;}
  .time{font-family:monospace;font-size:16px;color:#fff;min-width:78px;text-align:center;}
  .bar{position:relative;flex:1;height:28px;display:flex;align-items:center;}
  .track{width:100%;height:6px;background:rgba(255,255,255,.22);border-radius:99px;overflow:hidden;}
  .fill{height:100%;width:0;background:var(--red);}
  .status{position:fixed;left:18px;bottom:78px;z-index:12;max-width:calc(100vw - 36px);padding:10px 12px;background:rgba(20,0,5,.9);border:1px solid rgba(227,25,55,.55);border-radius:7px;color:#ffd2d8;font-family:monospace;font-size:13px;white-space:pre-wrap;display:none;}
  .hidden-ui .top,.hidden-ui .controls,.hidden-ui .center{opacity:0;pointer-events:none;}
</style>
</head>
<body>
<div class="stage" id="stage"></div>
<div class="top">
  <a class="back" href="/">Back</a>
  <div class="title">{{stream_title}}</div>
</div>
<div class="center">
  <button class="bigbtn skip" id="back15">-15</button>
  <button class="bigbtn" id="playPause">Play</button>
  <button class="bigbtn skip" id="fwd15">+15</button>
</div>
<div class="controls">
  <button class="ctlbtn" id="ctlPlay">Play</button>
  <span class="time" id="elapsed">0:00</span>
  <div class="bar"><div class="track"><div class="fill" id="fill"></div></div></div>
  <button class="ctlbtn" id="restart">Start</button>
</div>
<div class="status" id="status">{{error_msg}}</div>
<script>
(function () {
  var streamUrl = {{stream_url_json}};
  var originalUrl = {{original_url_json}};
  var quality = {{video_quality_json}};
  var profile = {{profile_json}};
  var seekS = parseInt("{{seek_s}}", 10) || 0;
  OGVLoader.base = "/ogv-dist";
  function ProgressiveOgvStream(url) {
    this.url = url;
    this.length = -1;
    this.loaded = false;
    this.loading = false;
    this.seekable = false;
    this.buffering = false;
    this.seeking = false;
    this.headers = {};
    this.offset = 0;
    this.eof = false;
    this._writeOffset = 0;
    this._chunks = [];
    this._waiters = [];
    this._error = null;
    this._abort = null;
  }
  ProgressiveOgvStream.prototype._notify = function () {
    var waiters = this._waiters.splice(0);
    for (var i = 0; i < waiters.length; i++) waiters[i]();
  };
  ProgressiveOgvStream.prototype._append = function (buf) {
    if (!buf || !buf.byteLength) return;
    this._chunks.push({start: this._writeOffset, end: this._writeOffset + buf.byteLength, bytes: new Uint8Array(buf)});
    this._writeOffset += buf.byteLength;
    this._notify();
  };
  ProgressiveOgvStream.prototype.load = function () {
    var self = this;
    if (self.loading) throw new Error("cannot load when loading");
    if (self.loaded) throw new Error("cannot load when loaded");
    self.loading = true;
    self._abort = window.AbortController ? new AbortController() : null;
    return fetch(self.url, {cache: "no-store", signal: self._abort ? self._abort.signal : undefined})
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP error " + resp.status);
        resp.headers.forEach(function (value, key) { self.headers[key.toLowerCase()] = value; });
        var len = parseInt(resp.headers.get("Content-Length") || "-1", 10);
        self.length = isFinite(len) && len >= 0 ? len : -1;
        self.loaded = true;
        self.loading = false;
        if (!resp.body || !resp.body.getReader) {
          return resp.arrayBuffer().then(function (buf) {
            self._append(buf);
            self.eof = true;
            self._notify();
          });
        }
        var reader = resp.body.getReader();
        function pump() {
          return reader.read().then(function (result) {
            if (result.done) {
              self.eof = true;
              self._notify();
              return;
            }
            self._append(result.value.buffer.slice(result.value.byteOffset, result.value.byteOffset + result.value.byteLength));
            return pump();
          });
        }
        pump().catch(function (err) {
          self._error = err;
          self.eof = true;
          self._notify();
        });
      })
      .catch(function (err) {
        self.loading = false;
        self._error = err;
        throw err;
      });
  };
  ProgressiveOgvStream.prototype.bytesAvailable = function (max) {
    max = max === undefined ? Infinity : max;
    var cursor = this.offset;
    var available = 0;
    for (var i = 0; i < this._chunks.length && available < max; i++) {
      var chunk = this._chunks[i];
      if (chunk.end <= cursor) continue;
      if (chunk.start > cursor) break;
      var take = Math.min(chunk.end - cursor, max - available);
      available += take;
      cursor += take;
    }
    return available;
  };
  ProgressiveOgvStream.prototype.buffer = function (bytes) {
    var self = this;
    return new Promise(function (resolve, reject) {
      function check() {
        if (self._error) {
          reject(self._error);
          return;
        }
        var available = self.bytesAvailable(bytes);
        if (available >= bytes || self.eof) {
          resolve(available);
          return;
        }
        self._waiters.push(check);
      }
      check();
    });
  };
  ProgressiveOgvStream.prototype.readBytes = function (target) {
    if (!(target instanceof Uint8Array)) throw new Error("invalid input");
    var requested = target.byteLength;
    var available = this.bytesAvailable(requested);
    var copied = 0;
    while (copied < available && this._chunks.length) {
      var chunk = this._chunks[0];
      if (chunk.end <= this.offset) {
        this._chunks.shift();
        continue;
      }
      if (chunk.start > this.offset) break;
      var chunkOffset = this.offset - chunk.start;
      var take = Math.min(chunk.end - this.offset, available - copied);
      target.set(chunk.bytes.subarray(chunkOffset, chunkOffset + take), copied);
      copied += take;
      this.offset += take;
      if (this.offset >= chunk.end) this._chunks.shift();
    }
    return copied;
  };
  ProgressiveOgvStream.prototype.readSync = function (bytes) {
    var count = this.bytesAvailable(bytes);
    var out = new Uint8Array(count);
    var read = this.readBytes(out);
    if (read !== count) throw new Error("failed to read expected data");
    return out.buffer;
  };
  ProgressiveOgvStream.prototype.read = function (bytes) {
    var self = this;
    return self.buffer(bytes).then(function () { return self.readSync(bytes); });
  };
  ProgressiveOgvStream.prototype.seek = function () {
    return Promise.reject(new Error("seek on non-seekable stream"));
  };
  ProgressiveOgvStream.prototype.abort = function () {
    if (this._abort) this._abort.abort();
    this.eof = true;
    this._notify();
  };
  ProgressiveOgvStream.prototype.getBufferedRanges = function () {
    return this._chunks.map(function (chunk) { return [chunk.start, chunk.end]; });
  };

  var progressiveStream = new ProgressiveOgvStream(streamUrl);
  var player = new OGVPlayer({base: "/ogv-dist", stream: progressiveStream});
  var stage = document.getElementById("stage");
  var statusEl = document.getElementById("status");
  var playBtn = document.getElementById("playPause");
  var ctlPlay = document.getElementById("ctlPlay");
  var elapsed = document.getElementById("elapsed");
  var fill = document.getElementById("fill");
  var hideTimer = null;

  player.id = "player";
  player.src = streamUrl;
  stage.appendChild(player);

  function showStatus(msg) {
    if (!msg) return;
    statusEl.style.display = "block";
    statusEl.textContent = msg;
  }
  showStatus({{error_msg_json}});

  function fmt(s) {
    s = Math.max(0, Math.floor(s || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (h) return h + ":" + (m < 10 ? "0" : "") + m + ":" + (sec < 10 ? "0" : "") + sec;
    return m + ":" + (sec < 10 ? "0" : "") + sec;
  }
  function updateButtons() {
    var label = player.paused ? "Play" : "Pause";
    playBtn.textContent = label;
    ctlPlay.textContent = label;
  }
  function clearStatus() {
    statusEl.style.display = "none";
    statusEl.textContent = "";
  }
  function streamDiagnosticUrl() {
    return streamUrl + (streamUrl.indexOf("?") === -1 ? "?" : "&") + "diagnostic=1";
  }
  function diagnoseFailure(prefix) {
    if (!window.fetch) {
      showStatus(prefix || "OGV playback failed. Try MP4 or MJPEG fallback for this source.");
      return;
    }
    fetch(streamDiagnosticUrl(), {cache: "no-store"})
      .then(function (resp) {
        return resp.text().then(function (text) {
          try { return JSON.parse(text); }
          catch (e) {
            return {
              ok: false,
              stage: "http",
              error: "HTTP " + resp.status + (text ? ": " + text.slice(0, 500) : "")
            };
          }
        });
      })
      .then(function (data) {
        var msg = prefix || "OGV playback failed.";
        if (data && data.stage) msg += "\\nstage: " + data.stage;
        if (data && data.error) msg += "\\nerror: " + data.error;
        showStatus(msg);
      })
      .catch(function () {
        showStatus(prefix || "OGV playback failed. Try MP4 or MJPEG fallback for this source.");
      });
  }
  function playNow() {
    clearStatus();
    try {
      var p = player.play();
      if (p && p.catch) {
        p.catch(function (err) {
          var msg = "Tap Play to start. This browser blocks autoplay until a user gesture.";
          if (err && err.message && err.message.indexOf("error streaming") !== -1) {
            diagnoseFailure("OGV network stream failed while opening.");
            return;
          }
          if (err && err.name && err.name !== "NotAllowedError") msg = "Playback could not start: " + err.name;
          showStatus(msg);
          updateButtons();
        });
      }
    } catch(e) {
      showStatus("Playback could not start: " + (e && e.message ? e.message : e));
    }
  }
  function togglePlay() {
    if (player.paused) playNow();
    else player.pause();
    updateButtons();
  }
  function reloadAt(pos) {
    if (!originalUrl) return;
    var target = "/watch?url=" + encodeURIComponent(originalUrl) +
      "&mode=ogv&seek=" + Math.max(0, Math.floor(pos));
    if (quality) target += "&quality=" + encodeURIComponent(quality);
    if (profile) target += "&profile=" + encodeURIComponent(profile);
    window.location.href = target;
  }
  function bump(delta) {
    if (originalUrl) {
      reloadAt(seekS + (player.currentTime || 0) + delta);
    } else if (isFinite(player.duration) && player.duration > 0) {
      player.currentTime = Math.max(0, Math.min(player.duration - 1, player.currentTime + delta));
    }
  }
  function reveal() {
    document.body.classList.remove("hidden-ui");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () { document.body.classList.add("hidden-ui"); }, 3500);
  }

  playBtn.addEventListener("click", togglePlay);
  ctlPlay.addEventListener("click", togglePlay);
  stage.addEventListener("click", function () { reveal(); });
  document.getElementById("back15").addEventListener("click", function () { bump(-15); });
  document.getElementById("fwd15").addEventListener("click", function () { bump(15); });
  document.getElementById("restart").addEventListener("click", function () { reloadAt(0); });
  player.addEventListener("play", updateButtons);
  player.addEventListener("playing", function () { clearStatus(); updateButtons(); });
  player.addEventListener("pause", updateButtons);
  player.addEventListener("ended", updateButtons);
  player.addEventListener("error", function () {
    diagnoseFailure("OGV playback failed. Try MP4 or MJPEG fallback for this source.");
  });
  window.addEventListener("unhandledrejection", function (event) {
    var reason = event && event.reason;
    if (reason && reason.name === "NotAllowedError") {
      showStatus("Tap Play to start. This browser blocks autoplay until a user gesture.");
      if (event.preventDefault) event.preventDefault();
      return;
    }
    if (reason && reason.message && reason.message.indexOf("error streaming") !== -1) {
      diagnoseFailure("OGV network stream failed while opening.");
      if (event.preventDefault) event.preventDefault();
    }
  });
  window.addEventListener("click", reveal, true);
  window.addEventListener("touchstart", reveal, true);

  setInterval(function () {
    var now = seekS + (player.currentTime || 0);
    elapsed.textContent = fmt(now);
    if (isFinite(player.duration) && player.duration > 0) {
      fill.style.width = Math.max(0, Math.min(100, (player.currentTime / player.duration) * 100)) + "%";
    }
  }, 500);

  showStatus("Tap Play to start.");
  reveal();
})();
</script>
</body>
</html>"""


def render_status_page() -> str:
    streams = registry.all_streams()
    if not streams:
        streams_html = '<p class="empty">No active streams</p>'
    else:
        rows = []
        for s in sorted(streams, key=lambda x: x.created_at, reverse=True):
            title = (s.title or s.url[:60] + "…").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            stream_url = f"/watch?url={quote(s.url, safe='')}"
            quality_tag = ""
            if s.quality:
                stream_url += f"&quality={s.quality}"
                quality_tag = f" · {s.quality}p"
            rows.append(
                f'<div class="stream-row">'
                f'<div><a href="{stream_url}">{title}{quality_tag}</a></div>'
                f'<div style="display:flex;align-items:center;gap:10px;">'
                f'<span class="badge {s.status}">{s.status.upper()}</span>'
                f'<button onclick="stopStream(\'{s.id}\')" title="Stop stream" '
                f'style="background:none;border:none;color:var(--muted);font-size:1.1rem;cursor:pointer;padding:0;line-height:1;" '
                f'onmouseover="this.style.color=\'var(--red)\'" onmouseout="this.style.color=\'var(--muted)\'">✕</button>'
                f'</div>'
                f'</div>'
            )
        streams_html = "\n".join(rows)

    subs_status = "loaded" if os.path.isfile(SUBSCRIPTIONS_FILE) else "not mounted"
    iptv_status = "mounted" if os.path.isdir(IPTV_LISTS_DIR) else "not mounted"
    return (STATUS_HTML
            .replace("{{stream_count}}", str(len(streams)))
            .replace("{{streams_html}}", streams_html)
            .replace("{{fps}}", str(MJPEG_FPS))
            .replace("{{quality}}", str(FFMPEG_QUALITY))
            .replace("{{width}}", str(STREAM_WIDTH))
            .replace("{{height}}", str(STREAM_HEIGHT))
            .replace("{{mp4_width}}", str(MP4_WIDTH))
            .replace("{{mp4_height}}", str(MP4_HEIGHT))
            .replace("{{mp4_bitrate}}", MP4_VIDEO_BITRATE)
            .replace("{{ogv_width}}", str(OGV_WIDTH))
            .replace("{{ogv_height}}", str(OGV_HEIGHT))
            .replace("{{ogv_fps}}", str(OGV_FPS))
            .replace("{{h264_encoder}}", _select_h264_encoder())
            .replace("{{hwaccel}}", " ".join(_ffmpeg_hwaccel_args()) or "none")
            .replace("{{max_streams}}", str(MAX_STREAMS))
            .replace("{{audio_delay_ms}}", str(AUDIO_DELAY_MS))
            .replace("{{local_media_video_delay_ms}}", str(LOCAL_MEDIA_VIDEO_DELAY_MS))
            .replace("{{subs_status}}", subs_status)
            .replace("{{iptv_status}}", iptv_status)
            .replace("{{pluto_langs}}", ", ".join(PLUTO_LANGS))
            .replace("{{pluto_langs_json}}", json.dumps(PLUTO_LANGS))
            .replace("{{local_media_dir}}", LOCAL_MEDIA_DIR))

def render_watch_page(stream_id: str, sync_ms: int, video_url: str = "", quality: int | None = None,
                      local_file: str = "", seek_s: int = 0) -> str:
    return (WATCH_HTML
            .replace("{{stream_id}}", stream_id)
            .replace("{{sync_ms}}", str(sync_ms))
            .replace("{{video_url}}", video_url)
            .replace("{{video_quality}}", str(quality or ""))
            .replace("{{local_file}}", local_file)
            .replace("{{seek_s}}", str(seek_s)))

def render_audio_page(stream_id: str, sync_ms: int, video_url: str = "", seek_s: int = 0, duration_s: int = 0) -> str:
    return (AUDIO_WATCH_HTML
            .replace("{{stream_id}}", stream_id)
            .replace("{{sync_ms}}", str(sync_ms))
            .replace("{{video_url}}", video_url)
            .replace("{{seek_s}}", str(seek_s))
            .replace("{{duration_s}}", str(duration_s)))

def render_mp4_page(direct_url: str, error_msg: str = "", stream_title: str = "") -> str:
    return (MP4_WATCH_HTML
            .replace("{{direct_url}}", direct_url)
            .replace("{{stream_title}}", stream_title)
            .replace("{{error_msg}}", error_msg))


def render_ogv_page(
    stream_url: str,
    original_url: str = "",
    error_msg: str = "",
    stream_title: str = "",
    quality: int | None = None,
    seek_s: int = 0,
    profile: str | None = None,
) -> str:
    safe_title = (stream_title or "OGV stream").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_error = (error_msg or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (OGV_WATCH_HTML
            .replace("{{stream_url_json}}", json.dumps(stream_url))
            .replace("{{original_url_json}}", json.dumps(original_url))
            .replace("{{stream_title}}", safe_title)
            .replace("{{error_msg}}", safe_error)
            .replace("{{error_msg_json}}", json.dumps(error_msg or ""))
            .replace("{{video_quality_json}}", json.dumps(str(quality or "")))
            .replace("{{profile_json}}", json.dumps(profile or ""))
            .replace("{{seek_s}}", str(seek_s)))

