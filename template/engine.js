/* Scene engine: one GSAP timeline driven by the program clock.
 *
 * Preview:  the program video plays with its sound; the timeline follows video.currentTime.
 * Render:   ?still — nothing plays; render.mjs calls window.__scene.render(t) for every frame.
 * Keys:     Space play/pause · ←/→ 5 s · R restart · M mute effects
 * URL:      ?t=12.5 freeze at 12.5 s · ?src=FILE program video (default ../work/proxy.mp4, "none" for no video)
 *           ?demo built-in demo program (no project needed) · ?still render mode · ?nohud hide the timecode
 *
 * script.js defines window.buildScene(api) and adds tweens to api.TL at times from api.at('spoken phrase').
 */
(() => {
  const Q = new URLSearchParams(location.search);
  const STILL = Q.has('still'), DEMO = Q.has('demo');
  const body = document.body;

  if (STILL) {
    body.classList.add('still-mode');
  }

  function defaultEdits() {
    return {
      version: 1,
      aspect: "9:16",
      stage: { width: 1080, height: 1920 },
      subtitles: {
        enabled: true,
        x: 0.5,
        y: 0.78,
        fontSize: 56,
        color: "#ffffff",
        bgColor: "rgba(15, 17, 22, 0.78)",
        uppercase: false,
        overrides: {}
      },
      speed_ranges: [],
      media_overlays: [],
      audio_clips: []
    };
  }

  let currentEdits = defaultEdits();
  let W = +body.dataset.w || 1920, H = +body.dataset.h || 1080;
  const stage = document.querySelector('#stage');
  const video = document.querySelector('#v');
  const subtitlesBox = document.querySelector('#subtitles-box');
  const subText = subtitlesBox ? subtitlesBox.querySelector('.sub-text') : null;
  const overlaysLayer = document.querySelector('#overlays-layer');

  /* ---- stage: fixed design size, scaled to the window ---- */
  stage.style.width = W + 'px';
  stage.style.height = H + 'px';
  const fit = () => {
    const s = Math.min(innerWidth / W, innerHeight / H);
    stage.style.transform = `translate(${(innerWidth - W * s) / 2}px, ${(innerHeight - H * s) / 2}px) scale(${s})`;
  };
  addEventListener('resize', fit);
  fit();

  function updateStageSize(w, h) {
    W = w; H = h;
    body.dataset.w = String(W);
    body.dataset.h = String(H);
    stage.style.width = W + 'px';
    stage.style.height = H + 'px';
    const bgLines = document.querySelector('#bgLines');
    if (bgLines) {
      bgLines.setAttribute('width', W);
      bgLines.setAttribute('height', H);
    }
    fit();
  }

  const TL = gsap.timeline({ paused: true });
  const SFX = [], baseSFX = [], missing = [], ASSETS = [], frameHooks = [];
  let PROGRAM = null, duration = 0, words = [], normWords = [];
  let subtitleCues = [];

  const norm = (s) => s.toLocaleLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}]+/gu, '');

  function updateCues() {
    if (typeof window.chunkThreeWords === 'function') {
      subtitleCues = window.chunkThreeWords(
        words,
        currentEdits.subtitles?.overrides || {},
        !!currentEdits.subtitles?.uppercase
      );
    } else {
      subtitleCues = [];
    }
  }

  function syncSfx() {
    SFX.length = 0;
    SFX.push(...baseSFX);
    for (const clip of currentEdits.audio_clips || []) {
      if (clip.type === 'sfx') {
        SFX.push({
          t: +Number(clip.start).toFixed(3),
          name: clip.name,
          gain: clip.gain || 0
        });
      }
    }
    SFX.sort((a, b) => a.t - b.t);
  }

  /* at('phrase'): time just before the first word of the phrase is spoken (lead 0.1 s). */
  function at(phrase, opt = {}) {
    const want = phrase.split(/\s+/).map(norm).filter(Boolean);
    const from = opt.from ?? 0, lead = opt.lead ?? 0.1;
    for (let i = 0; i + want.length <= normWords.length; i++) {
      if (words[i][0] < from) continue;
      let ok = true;
      for (let k = 0; k < want.length && ok; k++) ok = normWords[i + k] === want[k] || (k === want.length - 1 && normWords[i + k].startsWith(want[k]));
      if (ok) return opt.end ? words[i + want.length - 1][1] + 0.05 : Math.max(0, words[i][0] - lead);
    }
    missing.push(phrase);
    return null;
  }

  /* cue(t, 'whoosh', gainDb): a sound effect at program time t. */
  function cue(t, name, gain = 0) {
    if (t == null) return;
    const item = { t: +t.toFixed(3), name, gain };
    baseSFX.push(item);
    syncSfx();
  }

  /* ---- preview sound: effects play live through WebAudio ---- */
  let actx = null, muted = Q.has('mute');
  const buffers = {};
  async function loadSfx() {
    if (STILL || !SFX.length) return;
    if (!actx) actx = new AudioContext();
    for (const name of new Set(SFX.map((c) => c.name))) {
      try {
        const r = await fetch(`sfx/${name}.wav`);
        if (r.ok) buffers[name] = await actx.decodeAudioData(await r.arrayBuffer());
      } catch (e) { /* missing effect file */ }
    }
  }
  function playCue(c) {
    if (muted || !actx || !buffers[c.name]) return;
    if (actx.state === 'suspended') actx.resume();
    const src = actx.createBufferSource(), g = actx.createGain();
    src.buffer = buffers[c.name];
    g.gain.value = Math.pow(10, (c.gain || 0) / 20);
    src.connect(g).connect(actx.destination);
    src.start();
  }

  /* ---- clock ---- */
  let clock = 0, last = performance.now(), playing = false, prevClock = 0;
  const hasVideo = () => video && video.src && !video.dataset.none;

  function updateOverlays(t) {
    if (!overlaysLayer) return;
    const overlays = currentEdits.media_overlays || [];
    const activeIds = new Set(overlays.map((o) => o.id));

    Array.from(overlaysLayer.children).forEach((el) => {
      if (!activeIds.has(el.dataset.id)) {
        overlaysLayer.removeChild(el);
      }
    });

    overlays.forEach((ov) => {
      let el = overlaysLayer.querySelector(`[data-id="${ov.id}"]`);
      if (!el) {
        el = document.createElement('div');
        el.className = 'media-overlay-item';
        el.dataset.id = ov.id;
        if (ov.type === 'video') {
          const v = document.createElement('video');
          v.playsInline = true;
          v.preload = 'auto';
          v.muted = true;
          v.src = ov.url;
          el.appendChild(v);
        } else {
          const img = document.createElement('img');
          img.src = ov.url;
          el.appendChild(img);
        }

        // Corner resize handles (hidden in .still-mode)
        ['tl', 'tr', 'bl', 'br'].forEach((corner) => {
          const resizer = document.createElement('div');
          resizer.className = `resizer ${corner}`;
          resizer.dataset.resize = corner;
          el.appendChild(resizer);
        });

        overlaysLayer.appendChild(el);
      }

      const isActive = t >= ov.start && t <= ov.end;
      if (isActive) {
        el.style.display = 'block';
        el.style.visibility = 'visible';
        const xPct = (ov.x != null ? ov.x : 0.5) * 100;
        const yPct = (ov.y != null ? ov.y : 0.5) * 100;
        const wPct = (ov.width != null ? ov.width : 0.4) * 100;
        const hPct = (ov.height != null ? ov.height : 0.3) * 100;
        el.style.left = `${xPct}%`;
        el.style.top = `${yPct}%`;
        el.style.width = `${wPct}%`;
        el.style.height = `${hPct}%`;
        el.style.transform = 'translate(-50%, -50%)';

        const mediaEl = el.querySelector('video') || (el.tagName === 'VIDEO' ? el : null);
        if (!STILL && mediaEl) {
          const targetTime = Math.max(0, t - ov.start + (ov.trim_start || 0));
          if (playing && mediaEl.paused) {
            mediaEl.play().catch(() => {});
          } else if (!playing && !mediaEl.paused) {
            mediaEl.pause();
          }
          const driftThreshold = playing ? 0.25 : 0.03;
          if (Math.abs(mediaEl.currentTime - targetTime) > driftThreshold) {
            mediaEl.currentTime = targetTime;
          }
        }
      } else {
        el.style.display = 'none';
        el.style.visibility = 'hidden';
        const mediaEl = el.querySelector('video') || (el.tagName === 'VIDEO' ? el : null);
        if (mediaEl && !mediaEl.paused) {
          mediaEl.pause();
        }
      }
    });
  }

  function apply(t) {
    TL.seek(Math.max(1e-4, Math.min(t, TL.duration() || t)), false);

    // Render 3-word subtitles box
    const subCfg = currentEdits.subtitles || {};
    if (subCfg.enabled !== false && subtitlesBox && subText) {
      const cue = subtitleCues.find((c) => t >= c.start && t <= c.end);
      if (cue) {
        subText.textContent = cue.text;
        const xPct = (subCfg.x != null ? subCfg.x : 0.5) * 100;
        const yPct = (subCfg.y != null ? subCfg.y : 0.78) * 100;
        subtitlesBox.style.left = `${xPct}%`;
        subtitlesBox.style.top = `${yPct}%`;
        subtitlesBox.style.transform = 'translate(-50%, -50%)';
        subtitlesBox.style.fontSize = `${subCfg.fontSize || 56}px`;
        subtitlesBox.style.color = subCfg.color || '#ffffff';
        subtitlesBox.style.backgroundColor = subCfg.bgColor || 'rgba(15, 17, 22, 0.78)';
        subtitlesBox.style.visibility = 'visible';
        subtitlesBox.style.opacity = '1';
        subtitlesBox.style.display = 'block';
      } else {
        subtitlesBox.style.visibility = 'hidden';
        subtitlesBox.style.opacity = '0';
      }
    } else if (subtitlesBox) {
      subtitlesBox.style.visibility = 'hidden';
      subtitlesBox.style.opacity = '0';
      subtitlesBox.style.display = 'none';
    }

    // Render media overlays
    updateOverlays(t);

    frameHooks.forEach((f) => f(t));
  }

  function tick(now) {
    const dt = (now - last) / 1000;
    last = now;
    if (playing) {
      if (hasVideo()) {
        const vt = video.currentTime;
        if (video.paused || video.seeking) clock = vt;
        else if (Math.abs(vt - clock) > 0.25) clock = vt;
        else clock += dt + (vt - clock) * 0.03;

        // Apply speed ranges
        const activeSpeed = (currentEdits.speed_ranges || []).find((sr) => clock >= sr.start && clock <= sr.end);
        const targetRate = activeSpeed && activeSpeed.speed ? activeSpeed.speed : 1.0;
        if (video.playbackRate !== targetRate) {
          video.playbackRate = targetRate;
        }
      } else {
        clock += dt;
      }
      if (clock >= duration) { clock = duration; playing = false; if (hasVideo()) video.pause(); }
      for (const c of SFX) if (c.t > prevClock && c.t <= clock) playCue(c);
    }
    prevClock = clock;
    apply(clock);
    hud();
    requestAnimationFrame(tick);
  }

  function play() {
    playing = !playing;
    if (hasVideo()) playing ? video.play() : video.pause();
  }

  function seek(t) {
    clock = prevClock = Math.max(0, Math.min(duration, t));
    if (hasVideo()) video.currentTime = clock;
    apply(clock);
  }

  /* ---- render mode: one exact frame per call ---- */
  async function seekVideoOverlays(t) {
    if (!overlaysLayer) return;
    const overlays = currentEdits.media_overlays || [];
    for (const ov of overlays) {
      if (ov.type === 'video' && t >= ov.start && t <= ov.end) {
        const item = overlaysLayer.querySelector(`[data-id="${ov.id}"]`);
        const el = item ? (item.tagName === 'VIDEO' ? item : item.querySelector('video')) : null;
        if (el) {
          const targetTime = Math.max(0, t - ov.start + (ov.trim_start || 0));
          if (Math.abs(el.currentTime - targetTime) > 0.001) {
            await new Promise((res) => {
              el.addEventListener('seeked', res, { once: true });
              el.currentTime = targetTime;
            });
          }
          if (el.readyState < 2) {
            await new Promise((res) => el.addEventListener('canplay', res, { once: true }));
          }
        }
      }
    }
  }

  async function render(t) {
    playing = false;
    if (hasVideo()) {
      video.pause();
      if (Math.abs(video.currentTime - t) > 0.0005) {
        await new Promise((res) => { video.addEventListener('seeked', res, { once: true }); video.currentTime = t; });
      }
      if (video.readyState < 2) await new Promise((res) => video.addEventListener('canplay', res, { once: true }));
    }
    apply(t);
    await seekVideoOverlays(t);
    await Promise.all(ASSETS);
    clock = t;
    return true;
  }

  /* ---- HUD (preview only) ---- */
  const hudEl = document.querySelector('#hud');
  function hud() {
    if (!hudEl || STILL || Q.has('nohud')) return;
    const m = Math.floor(clock / 60), s = (clock % 60).toFixed(2).padStart(5, '0');
    hudEl.textContent = `${m}:${s} / ${(duration / 60) | 0}:${String(Math.round(duration % 60)).padStart(2, '0')}` +
      (missing.length ? `   ·   ${missing.length} phrase(s) not found: ${missing.slice(0, 3).join(' | ')}` : '') +
      (playing ? '' : '   ·   Space to play');
  }

  addEventListener('keydown', (e) => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    if (e.code === 'Space') { e.preventDefault(); play(); }
    else if (e.code === 'ArrowRight') seek(clock + 5);
    else if (e.code === 'ArrowLeft') seek(clock - 5);
    else if (e.code === 'KeyR') seek(0);
    else if (e.code === 'KeyM') muted = !muted;
  });

  /* ---- boot ---- */
  async function loadProgram() {
    if (DEMO) return window.DEMO_PROGRAM;
    try {
      const r = await fetch(Q.get('program') || '../work/program.json', { cache: 'no-store' });
      if (r.ok) return await r.json();
    } catch (e) { /* no project yet */ }
    return window.DEMO_PROGRAM;
  }

  async function loadEdits() {
    try {
      const r = await fetch('/api/edits', { cache: 'no-store' });
      if (r.ok) return await r.json();
    } catch (e) {}
    try {
      const r2 = await fetch('../work/edits.json', { cache: 'no-store' });
      if (r2.ok) return await r2.json();
    } catch (e) {}
    return defaultEdits();
  }

  (async () => {
    PROGRAM = await loadProgram();
    currentEdits = await loadEdits();

    if (currentEdits.stage?.width && currentEdits.stage?.height) {
      updateStageSize(currentEdits.stage.width, currentEdits.stage.height);
    }

    words = (PROGRAM.words || []).map((w) => [w[0], w[1], w[2]]);
    normWords = words.map((w) => norm(w[2]));
    duration = PROGRAM.duration || (PROGRAM.frames / PROGRAM.fps) || 30;

    updateCues();
    syncSfx();

    const src = Q.get('src') || (PROGRAM === window.DEMO_PROGRAM ? 'none' : '../work/proxy.mp4');
    if (src === 'none') { video.dataset.none = '1'; video.removeAttribute('src'); video.style.display = 'none'; }
    else {
      video.src = src;
      video.muted = STILL;
      ASSETS.push(new Promise((res) => (video.readyState >= 1 ? res() : video.addEventListener('loadedmetadata', res, { once: true }))));
    }
    if (document.fonts) ASSETS.push(document.fonts.ready);

    window.buildScene({ TL, at, cue, words, chapters: PROGRAM.chapters || [], duration, W, H, stage, ASSETS,
      onFrame: (f) => frameHooks.push(f), still: STILL });
    if (TL.duration() < duration) TL.set({}, {}, duration);

    window.__scene = {
      render,
      SFX,
      missing,
      duration,
      TL,
      fps: PROGRAM.fps || 30,
      applyEdits: (nextEdits) => {
        currentEdits = nextEdits;
        if (currentEdits.stage?.width && currentEdits.stage?.height) {
          updateStageSize(currentEdits.stage.width, currentEdits.stage.height);
        }
        updateCues();
        syncSfx();
        loadSfx();
        apply(clock);
      },
      getEdits: () => currentEdits,
      getCues: () => subtitleCues,
      seek: (t) => seek(t),
      play: () => play(),
      get clock() { return clock; }
    };
    window.__sceneReady = () => Promise.all(ASSETS);

    await loadSfx();

    // Initialize interactive editor if not in ?still mode
    if (!STILL && typeof window.__initEditor === 'function') {
      window.__initEditor(window.__scene, currentEdits);
    }

    const t0 = Q.has('t') ? +Q.get('t') : 0;
    if (STILL) { await render(t0); return; }
    seek(t0);
    requestAnimationFrame((n) => { last = n; tick(n); });
  })();
})();
