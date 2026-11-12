/* Antigravity Studio - Canva/CapCut Interactive Scene Engine & Layer/Undo Editor */
(() => {
  const MAX_WORDS = 3;
  const PAUSE_BREAK_SEC = 0.35;
  const PUNCT_BREAK = ['.', ',', '!', '?', ';', ':'];
  const MIN_DURATION_SEC = 0.2;

  /**
   * Browser-side 3-word subtitle chunker matching scripts/subtitles.py.
   * Breaks on max 3 words, punctuation (.,!?;:), silence gap >= 0.35s, or end of words.
   * Filters out punctuation-only or empty tokens.
   */
  function chunkThreeWords(words, overrides = {}, uppercase = false) {
    const validWords = (words || []).filter(
      (w) => Array.isArray(w) && w.length >= 3 && /[\p{L}\p{N}]/u.test(String(w[2]))
    );
    if (!validWords.length) return [];

    const cues = [];
    let current = [];
    let cueIdx = 0;

    for (let i = 0; i < validWords.length; i++) {
      const w = validWords[i];
      current.push(w);
      const wText = String(w[2]).trim();

      const reachedLimit = current.length >= MAX_WORDS;
      const cleanWord = wText.replace(/["'“”‘’]+$/g, '');
      const punctHit = /[.,!?;:]$/.test(cleanWord);
      let pauseHit = false;
      if (i + 1 < validWords.length) {
        const nextStart = Number(validWords[i + 1][0]);
        const currEnd = Number(w[1]);
        if (Math.round((nextStart - currEnd) * 1000) / 1000 >= PAUSE_BREAK_SEC) {
          pauseHit = true;
        }
      }
      const isLast = i === validWords.length - 1;

      if (reachedLimit || punctHit || pauseHit || isLast) {
        const cueId = `sub_${cueIdx}`;
        const start = Math.round(Number(current[0][0]) * 1000) / 1000;
        const rawEnd = Number(current[current.length - 1][1]);
        let end = Math.round(Math.max(rawEnd, start + MIN_DURATION_SEC) * 1000) / 1000;
        const nextWordStart = i + 1 < validWords.length ? Number(validWords[i + 1][0]) : null;
        if (nextWordStart !== null && nextWordStart > start) {
          end = Math.min(end, Math.round(nextWordStart * 1000) / 1000);
        }

        let text = current.map((item) => String(item[2]).trim()).join(' ');
        if (overrides && overrides[cueId] !== undefined) {
          text = overrides[cueId];
        }
        if (uppercase) {
          text = text.toUpperCase();
        }

        cues.push({
          id: cueId,
          start,
          end,
          text,
          words: current.map((item) => [...item]),
        });
        current = [];
        cueIdx++;
      }
    }
    return cues;
  }

  /**
   * 20-step Undo/Redo history manager with deep clone isolation.
   */
  function createHistoryManager(initialState, maxSteps = 20) {
    const clone = (s) => JSON.parse(JSON.stringify(s));
    const limit = Math.max(1, maxSteps || 20);
    let undoStack = [clone(initialState)];
    let redoStack = [];

    return {
      push(nextState) {
        undoStack.push(clone(nextState));
        while (undoStack.length > limit) {
          undoStack.shift();
        }
        redoStack = [];
      },
      undo() {
        if (undoStack.length > 1) {
          const curr = undoStack.pop();
          redoStack.push(curr);
        }
        return clone(undoStack[undoStack.length - 1]);
      },
      redo() {
        if (redoStack.length > 0) {
          const next = redoStack.pop();
          undoStack.push(next);
        }
        return clone(undoStack[undoStack.length - 1]);
      },
      canUndo() {
        return undoStack.length > 1;
      },
      canRedo() {
        return redoStack.length > 0;
      },
      current() {
        return clone(undoStack[undoStack.length - 1]);
      },
    };
  }

  // Export functions to globalThis / window
  const g = typeof window !== 'undefined' ? window : globalThis;
  g.chunkThreeWords = chunkThreeWords;
  g.createHistoryManager = createHistoryManager;

  // Check for ?still mode
  const Q = typeof location !== 'undefined' && location.search ? new URLSearchParams(location.search) : null;
  const isStill = Q && Q.has('still');

  if (typeof document !== 'undefined' && document.body && isStill) {
    document.body.classList.add('still-mode');
  }

  // If in still mode or no full DOM document, skip editor UI initialization
  if (isStill || typeof document === 'undefined' || !document.getElementById) {
    return;
  }

  /**
   * Interactive Canva/CapCut Studio Editor Controller
   */
  function initStudio(scene, initialEdits) {
    const editorUi = document.getElementById('editor-ui');
    const stage = document.getElementById('stage');
    const subtitlesBox = document.getElementById('subtitles-box');
    if (!editorUi || !stage) return;

    let edits = JSON.parse(JSON.stringify(initialEdits));
    const history = createHistoryManager(edits, 20);

    let activeTab = 'assets'; // 'assets' | 'sfx'
    let activeInspectorTab = 'subtitles'; // 'subtitles' | 'overlays' | 'speed'
    let selectedItem = null; // { type: 'subtitles' } | { type: 'overlay', id: '...' }
    let assetList = [];
    let sfxList = ['whoosh', 'soft-whoosh', 'tick', 'click', 'key', 'typing', 'pop', 'chime'];

    // Provide __editor namespace
    window.__editor = {
      pushHistory: (next) => history.push(next),
      undo: () => undoAction(),
      redo: () => redoAction(),
      canUndo: () => history.canUndo(),
      canRedo: () => history.canRedo(),
      getHistoryManager: () => history,
      save: () => saveEditsToServer(),
    };

    function showToast(msg) {
      let toast = document.querySelector('.editor-toast');
      if (!toast) {
        toast = document.createElement('div');
        toast.className = 'editor-toast';
        document.body.appendChild(toast);
      }
      toast.textContent = msg;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 2200);
    }

    let saveTimeout = null;
    function saveEditsToServer(quiet = false) {
      if (saveTimeout) clearTimeout(saveTimeout);
      fetch('/api/edits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(edits),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!quiet) showToast('Edits saved to work/edits.json');
        })
        .catch((err) => {
          console.warn('Could not save to /api/edits:', err);
        });
    }

    function saveEditsDebounced() {
      if (saveTimeout) clearTimeout(saveTimeout);
      saveTimeout = setTimeout(() => saveEditsToServer(true), 1200);
    }

    function applyChange(pushToHistory = true) {
      if (pushToHistory) {
        history.push(edits);
      }
      if (scene && typeof scene.applyEdits === 'function') {
        scene.applyEdits(edits);
      }
      saveEditsDebounced();
      renderInspector();
      renderTimelineTracks();
      updateHeaderButtons();
    }

    function undoAction() {
      if (!history.canUndo()) return;
      edits = history.undo();
      if (scene && typeof scene.applyEdits === 'function') {
        scene.applyEdits(edits);
      }
      saveEditsDebounced();
      renderAll();
      showToast('Undo');
    }

    function redoAction() {
      if (!history.canRedo()) return;
      edits = history.redo();
      if (scene && typeof scene.applyEdits === 'function') {
        scene.applyEdits(edits);
      }
      saveEditsDebounced();
      renderAll();
      showToast('Redo');
    }

    // Load assets from server
    function loadAssets() {
      fetch('/api/assets')
        .then((r) => r.json())
        .then((data) => {
          if (data.assets) assetList = data.assets;
          if (data.sfx) sfxList = data.sfx;
          renderLeftPanel();
        })
        .catch(() => {});
    }

    // Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) redoAction();
        else undoAction();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        redoAction();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        saveEditsToServer();
      }
    });

    // Build Editor UI Frame
    editorUi.innerHTML = `
      <div id="editor-header" class="interactive">
        <div class="brand-section">
          <span class="brand-badge">PRO</span>
          <span class="brand-title">Antigravity Studio</span>
        </div>
        <div class="header-center-tools">
          <button class="aspect-btn ${edits.aspect === '9:16' ? 'active' : ''}" id="aspect-9-16">9:16 (Shorts/Reels)</button>
          <button class="aspect-btn ${edits.aspect === '16:9' ? 'active' : ''}" id="aspect-16-9">16:9 (Landscape)</button>
        </div>
        <div class="header-actions">
          <button class="tool-btn" id="btn-undo" title="Undo (Ctrl+Z)">⤺ Undo</button>
          <button class="tool-btn" id="btn-redo" title="Redo (Ctrl+Y)">⤼ Redo</button>
          <button class="tool-btn primary" id="btn-save" title="Save (Ctrl+S)">💾 Save</button>
        </div>
      </div>

      <div id="editor-left-panel" class="interactive">
        <div class="panel-tabs">
          <div class="panel-tab ${activeTab === 'assets' ? 'active' : ''}" data-tab="assets">Assets</div>
          <div class="panel-tab ${activeTab === 'sfx' ? 'active' : ''}" data-tab="sfx">SFX Library</div>
        </div>
        <div class="panel-content" id="left-panel-content"></div>
      </div>

      <div id="editor-right-panel" class="interactive">
        <div class="panel-tabs">
          <div class="panel-tab ${activeInspectorTab === 'subtitles' ? 'active' : ''}" data-itab="subtitles">Subtitles</div>
          <div class="panel-tab ${activeInspectorTab === 'overlays' ? 'active' : ''}" data-itab="overlays">Overlays</div>
          <div class="panel-tab ${activeInspectorTab === 'speed' ? 'active' : ''}" data-itab="speed">Speed</div>
        </div>
        <div class="panel-content" id="right-panel-content"></div>
      </div>

      <div id="editor-bottom-panel" class="interactive">
        <div class="timeline-controls">
          <div class="playback-controls">
            <button class="play-btn" id="timeline-play-btn">▶</button>
            <span class="timecode-display" id="timeline-timecode">00:00.00 / 00:30.00</span>
          </div>
          <div class="timeline-quick-actions">
            <span style="font-size:11px;color:#8b949e;">Drag playhead to seek · Space to Play/Pause</span>
          </div>
        </div>
        <div class="timeline-tracks-area" id="timeline-tracks">
          <div class="timeline-playhead" id="timeline-playhead"></div>
          <div class="timeline-track" id="track-subs">
            <span class="timeline-track-label">3-Word Subtitles</span>
          </div>
          <div class="timeline-track" id="track-overlays">
            <span class="timeline-track-label">Media Overlays</span>
          </div>
          <div class="timeline-track" id="track-speed">
            <span class="timeline-track-label">Speed Ranges</span>
          </div>
        </div>
      </div>

      <!-- Hidden file input for uploads -->
      <input type="file" id="editor-file-input" style="display:none;" accept="image/*,video/*,audio/*" />
    `;

    // DOM References
    const btnUndo = document.getElementById('btn-undo');
    const btnRedo = document.getElementById('btn-redo');
    const btnSave = document.getElementById('btn-save');
    const btn916 = document.getElementById('aspect-9-16');
    const btn169 = document.getElementById('aspect-16-9');
    const leftContent = document.getElementById('left-panel-content');
    const rightContent = document.getElementById('right-panel-content');
    const playBtn = document.getElementById('timeline-play-btn');
    const timecodeDisplay = document.getElementById('timeline-timecode');
    const timelineTracks = document.getElementById('timeline-tracks');
    const playhead = document.getElementById('timeline-playhead');
    const fileInput = document.getElementById('editor-file-input');

    function updateHeaderButtons() {
      if (btnUndo) btnUndo.disabled = !history.canUndo();
      if (btnRedo) btnRedo.disabled = !history.canRedo();
      if (btn916 && btn169) {
        btn916.classList.toggle('active', edits.aspect === '9:16');
        btn169.classList.toggle('active', edits.aspect === '16:9');
      }
    }

    if (btnUndo) btnUndo.addEventListener('click', undoAction);
    if (btnRedo) btnRedo.addEventListener('click', redoAction);
    if (btnSave) btnSave.addEventListener('click', () => saveEditsToServer());

    // Aspect Toggle
    if (btn916) {
      btn916.addEventListener('click', () => {
        if (edits.aspect === '9:16') return;
        edits.aspect = '9:16';
        edits.stage = { width: 1080, height: 1920 };
        applyChange();
      });
    }
    if (btn169) {
      btn169.addEventListener('click', () => {
        if (edits.aspect === '16:9') return;
        edits.aspect = '16:9';
        edits.stage = { width: 1920, height: 1080 };
        applyChange();
      });
    }

    // Tabs
    editorUi.querySelectorAll('.panel-tab[data-tab]').forEach((tab) => {
      tab.addEventListener('click', () => {
        editorUi.querySelectorAll('.panel-tab[data-tab]').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        activeTab = tab.dataset.tab;
        renderLeftPanel();
      });
    });

    editorUi.querySelectorAll('.panel-tab[data-itab]').forEach((tab) => {
      tab.addEventListener('click', () => {
        editorUi.querySelectorAll('.panel-tab[data-itab]').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        activeInspectorTab = tab.dataset.itab;
        renderInspector();
      });
    });

    // Left Panel Render
    function renderLeftPanel() {
      if (!leftContent) return;
      if (activeTab === 'assets') {
        let html = `
          <div class="upload-box" id="upload-box-btn">
            <span style="font-size:20px;margin-bottom:4px;">☁️</span>
            <strong>Upload Media Asset</strong>
            <span>MP4, WebM, PNG, JPG, MP3, WAV</span>
          </div>
          <div class="asset-list">
        `;
        if (!assetList.length) {
          html += `<div style="font-size:12px;color:#8b949e;text-align:center;padding:20px 0;">No uploaded assets yet.<br>Click above to add files.</div>`;
        } else {
          assetList.forEach((a) => {
            html += `
              <div class="asset-card">
                <div class="asset-info">
                  <span class="asset-name" title="${a.name}">${a.name}</span>
                  <span class="asset-meta">${a.type}</span>
                </div>
                <button class="asset-add-btn" data-asset-url="${a.url}" data-asset-name="${a.name}" data-asset-type="${a.type}">+ Insert</button>
              </div>
            `;
          });
        }
        html += `</div>`;
        leftContent.innerHTML = html;

        const uploadBox = document.getElementById('upload-box-btn');
        if (uploadBox) {
          uploadBox.addEventListener('click', () => fileInput.click());
        }

        leftContent.querySelectorAll('.asset-add-btn').forEach((btn) => {
          btn.addEventListener('click', () => {
            const url = btn.dataset.assetUrl;
            const name = btn.dataset.assetName;
            const type = btn.dataset.assetType;
            const curClock = scene ? Math.max(0, scene.clock || 0) : 0;
            const duration = scene ? scene.duration || 30 : 30;

            if (type === 'image' || type === 'video') {
              const newOv = {
                id: `ov_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
                type,
                url,
                name,
                start: Math.round(curClock * 100) / 100,
                end: Math.round(Math.min(duration, curClock + 3) * 100) / 100,
                x: 0.5,
                y: 0.5,
                width: 0.4,
                height: 0.3,
                trim_start: 0,
              };
              if (!edits.media_overlays) edits.media_overlays = [];
              edits.media_overlays.push(newOv);
              selectedItem = { type: 'overlay', id: newOv.id };
              activeInspectorTab = 'overlays';
              editorUi.querySelectorAll('.panel-tab[data-itab]').forEach((t) => {
                t.classList.toggle('active', t.dataset.itab === 'overlays');
              });
              applyChange();
              showToast(`Inserted overlay ${name}`);
            } else if (type === 'audio') {
              const newClip = {
                id: `audio_${Date.now()}`,
                type: 'audio',
                url,
                name,
                start: Math.round(curClock * 100) / 100,
                gain: 0,
              };
              if (!edits.audio_clips) edits.audio_clips = [];
              edits.audio_clips.push(newClip);
              applyChange();
              showToast(`Inserted audio clip ${name}`);
            }
          });
        });
      } else if (activeTab === 'sfx') {
        let html = `<div class="asset-list">`;
        sfxList.forEach((s) => {
          html += `
            <div class="asset-card">
              <div class="asset-info">
                <span class="asset-name">🔔 ${s}</span>
                <span class="asset-meta">Sound Effect</span>
              </div>
              <button class="asset-add-btn" data-sfx="${s}">+ Cue at Playhead</button>
            </div>
          `;
        });
        html += `</div>`;
        leftContent.innerHTML = html;

        leftContent.querySelectorAll('.asset-add-btn[data-sfx]').forEach((btn) => {
          btn.addEventListener('click', () => {
            const sfxName = btn.dataset.sfx;
            const curClock = scene ? Math.max(0, scene.clock || 0) : 0;
            const newClip = {
              id: `sfx_${Date.now()}`,
              type: 'sfx',
              name: sfxName,
              start: Math.round(curClock * 1000) / 1000,
              gain: 0,
            };
            if (!edits.audio_clips) edits.audio_clips = [];
            edits.audio_clips.push(newClip);
            applyChange();
            showToast(`Added ${sfxName} cue at ${curClock.toFixed(2)}s`);
          });
        });
      }
    }

    // File Upload Handler
    if (fileInput) {
      fileInput.addEventListener('change', () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;
        const headers = { 'X-Filename': file.name };
        fetch('/api/assets', {
          method: 'POST',
          headers,
          body: file,
        })
          .then((r) => r.json())
          .then((data) => {
            if (data.ok) {
              showToast(`Uploaded ${data.asset.name}`);
              loadAssets();
            } else {
              showToast(`Upload failed: ${data.error || 'Unknown error'}`);
            }
          })
          .catch((err) => {
            showToast(`Upload failed: ${err.message}`);
          })
          .finally(() => {
            fileInput.value = '';
          });
      });
    }

    // Right Inspector Render
    function renderInspector() {
      if (!rightContent) return;
      if (activeInspectorTab === 'subtitles') {
        const sub = edits.subtitles || {};
        const cues = scene && typeof scene.getCues === 'function' ? scene.getCues() : [];

        let cuesHtml = '';
        cues.forEach((c) => {
          const isOverridden = sub.overrides && sub.overrides[c.id] !== undefined;
          cuesHtml += `
            <div class="cue-item" data-cue-id="${c.id}" data-cue-start="${c.start}">
              <span class="cue-time" title="Click to seek">${c.start.toFixed(1)}s</span>
              <input type="text" class="cue-input" value="${c.text}" data-cid="${c.id}" />
            </div>
          `;
        });

        rightContent.innerHTML = `
          <div class="inspector-section">
            <div class="inspector-title">
              <span>Subtitles Styling</span>
              <input type="checkbox" id="sub-enabled" ${sub.enabled !== false ? 'checked' : ''} />
            </div>
            <div class="prop-row">
              <span class="prop-label">Font Size</span>
              <input type="number" id="sub-font-size" class="prop-input" min="20" max="140" value="${sub.fontSize || 56}" />
            </div>
            <div class="prop-row">
              <span class="prop-label">Text Color</span>
              <input type="color" id="sub-color" class="prop-input" value="${sub.color || '#ffffff'}" />
            </div>
            <div class="prop-row">
              <span class="prop-label">Background</span>
              <input type="text" id="sub-bg-color" class="prop-input" style="width:130px;" value="${sub.bgColor || 'rgba(15, 17, 22, 0.78)'}" />
            </div>
            <div class="prop-row">
              <span class="prop-label">Uppercase</span>
              <input type="checkbox" id="sub-uppercase" ${sub.uppercase ? 'checked' : ''} />
            </div>
            <div class="prop-row">
              <span class="prop-label">Position Y</span>
              <input type="range" id="sub-y-slider" min="0.1" max="0.95" step="0.01" value="${sub.y || 0.78}" style="width:130px;" />
            </div>
          </div>

          <div class="inspector-section">
            <div class="inspector-title">
              <span>3-Word Cues (${cues.length})</span>
            </div>
            <div class="cues-list">
              ${cuesHtml || '<span style="color:#8b949e;font-size:11px;">No speech words found</span>'}
            </div>
          </div>
        `;

        // Subtitle bindings
        const chkEnabled = document.getElementById('sub-enabled');
        if (chkEnabled) {
          chkEnabled.addEventListener('change', () => {
            edits.subtitles.enabled = chkEnabled.checked;
            applyChange();
          });
        }
        const numFontSize = document.getElementById('sub-font-size');
        if (numFontSize) {
          numFontSize.addEventListener('input', () => {
            edits.subtitles.fontSize = Number(numFontSize.value) || 56;
            applyChange();
          });
        }
        const colColor = document.getElementById('sub-color');
        if (colColor) {
          colColor.addEventListener('input', () => {
            edits.subtitles.color = colColor.value;
            applyChange();
          });
        }
        const txtBg = document.getElementById('sub-bg-color');
        if (txtBg) {
          txtBg.addEventListener('change', () => {
            edits.subtitles.bgColor = txtBg.value;
            applyChange();
          });
        }
        const chkUpper = document.getElementById('sub-uppercase');
        if (chkUpper) {
          chkUpper.addEventListener('change', () => {
            edits.subtitles.uppercase = chkUpper.checked;
            applyChange();
          });
        }
        const ySlider = document.getElementById('sub-y-slider');
        if (ySlider) {
          ySlider.addEventListener('input', () => {
            edits.subtitles.y = Number(ySlider.value);
            applyChange();
          });
        }

        rightContent.querySelectorAll('.cue-time').forEach((el) => {
          el.addEventListener('click', () => {
            const parent = el.closest('.cue-item');
            const start = Number(parent.dataset.cueStart);
            if (scene && typeof scene.seek === 'function') {
              scene.seek(start);
            }
          });
        });

        rightContent.querySelectorAll('.cue-input').forEach((input) => {
          input.addEventListener('change', () => {
            const cid = input.dataset.cid;
            if (!edits.subtitles.overrides) edits.subtitles.overrides = {};
            edits.subtitles.overrides[cid] = input.value;
            applyChange();
          });
        });
      } else if (activeInspectorTab === 'overlays') {
        const overlays = edits.media_overlays || [];
        let html = `
          <div class="inspector-section">
            <div class="inspector-title">
              <span>Active Overlays (${overlays.length})</span>
            </div>
            <div class="cues-list" style="max-height:160px;">
        `;
        if (!overlays.length) {
          html += `<span style="color:#8b949e;font-size:11px;">No overlays added yet. Use the Left Asset Tray to insert media.</span>`;
        } else {
          overlays.forEach((ov) => {
            const isSel = selectedItem && selectedItem.id === ov.id;
            html += `
              <div class="cue-item ${isSel ? 'selected' : ''}" data-ov-id="${ov.id}" style="${isSel ? 'border-color:#3d8bff;background:rgba(61,139,255,0.12);' : ''}cursor:pointer;">
                <span class="cue-time" data-ov-seek="${ov.start}">${ov.start.toFixed(1)}s</span>
                <span style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;">${ov.name || ov.id}</span>
                <button style="background:none;border:none;color:#f0524d;cursor:pointer;" data-del-ov="${ov.id}">✕</button>
              </div>
            `;
          });
        }
        html += `</div></div>`;

        // If an overlay is selected, show its properties
        const selOv = selectedItem && overlays.find((o) => o.id === selectedItem.id);
        if (selOv) {
          html += `
            <div class="inspector-section">
              <div class="inspector-title">
                <span>Selected Overlay Properties</span>
              </div>
              <div class="prop-row">
                <span class="prop-label">Start (sec)</span>
                <input type="number" step="0.1" class="prop-input" id="ov-prop-start" value="${selOv.start}" />
              </div>
              <div class="prop-row">
                <span class="prop-label">End (sec)</span>
                <input type="number" step="0.1" class="prop-input" id="ov-prop-end" value="${selOv.end}" />
              </div>
              <div class="prop-row">
                <span class="prop-label">Width (%)</span>
                <input type="number" step="0.05" min="0.05" max="1" class="prop-input" id="ov-prop-w" value="${selOv.width}" />
              </div>
              <div class="prop-row">
                <span class="prop-label">Height (%)</span>
                <input type="number" step="0.05" min="0.05" max="1" class="prop-input" id="ov-prop-h" value="${selOv.height}" />
              </div>
              ${
                selOv.type === 'video'
                  ? `
                <div class="prop-row">
                  <span class="prop-label">Trim Start (sec)</span>
                  <input type="number" step="0.1" class="prop-input" id="ov-prop-trim" value="${selOv.trim_start || 0}" />
                </div>
              `
                  : ''
              }
            </div>
          `;
        }

        rightContent.innerHTML = html;

        rightContent.querySelectorAll('.cue-item[data-ov-id]').forEach((item) => {
          item.addEventListener('click', (e) => {
            if (e.target.closest('[data-del-ov]')) return;
            const id = item.dataset.ovId;
            selectedItem = { type: 'overlay', id };
            if (stage) {
              stage.querySelectorAll('.media-overlay-item').forEach((el) => {
                el.classList.toggle('selected', el.dataset.id === id);
              });
            }
            renderInspector();
          });
        });

        rightContent.querySelectorAll('[data-ov-seek]').forEach((btn) => {
          btn.addEventListener('click', () => {
            const t = Number(btn.dataset.ovSeek);
            if (scene && typeof scene.seek === 'function') scene.seek(t);
          });
        });

        rightContent.querySelectorAll('[data-del-ov]').forEach((btn) => {
          btn.addEventListener('click', () => {
            const id = btn.dataset.delOv;
            edits.media_overlays = edits.media_overlays.filter((o) => o.id !== id);
            if (selectedItem && selectedItem.id === id) selectedItem = null;
            applyChange();
          });
        });

        if (selOv) {
          const inpStart = document.getElementById('ov-prop-start');
          const inpEnd = document.getElementById('ov-prop-end');
          const inpW = document.getElementById('ov-prop-w');
          const inpH = document.getElementById('ov-prop-h');
          const inpTrim = document.getElementById('ov-prop-trim');

          if (inpStart) {
            inpStart.addEventListener('change', () => {
              selOv.start = Number(inpStart.value);
              applyChange();
            });
          }
          if (inpEnd) {
            inpEnd.addEventListener('change', () => {
              selOv.end = Number(inpEnd.value);
              applyChange();
            });
          }
          if (inpW) {
            inpW.addEventListener('input', () => {
              selOv.width = Number(inpW.value);
              applyChange();
            });
          }
          if (inpH) {
            inpH.addEventListener('input', () => {
              selOv.height = Number(inpH.value);
              applyChange();
            });
          }
          if (inpTrim) {
            inpTrim.addEventListener('change', () => {
              selOv.trim_start = Number(inpTrim.value);
              applyChange();
            });
          }
        }
      } else if (activeInspectorTab === 'speed') {
        const speeds = edits.speed_ranges || [];
        let html = `
          <div class="inspector-section">
            <div class="inspector-title">
              <span>Speed Segments (${speeds.length})</span>
              <button class="tool-btn" id="btn-add-speed" style="padding:2px 6px;font-size:11px;">+ Add</button>
            </div>
            <div class="cues-list">
        `;
        if (!speeds.length) {
          html += `<span style="color:#8b949e;font-size:11px;">No speed ranges defined. App plays at 1.0x normal speed.</span>`;
        } else {
          speeds.forEach((sr, idx) => {
            html += `
              <div class="cue-item">
                <input type="number" step="0.1" min="0" class="prop-input" data-spd-start="${idx}" value="${sr.start}" style="width:55px;" title="Start time (sec)" />
                <span style="color:#8b949e;font-size:11px;">-</span>
                <input type="number" step="0.1" min="0" class="prop-input" data-spd-end="${idx}" value="${sr.end}" style="width:55px;" title="End time (sec)" />
                <select class="prop-input" data-spd-idx="${idx}" style="padding:2px;font-size:11px;">
                  <option value="0.5" ${sr.speed === 0.5 ? 'selected' : ''}>0.5x</option>
                  <option value="0.75" ${sr.speed === 0.75 ? 'selected' : ''}>0.75x</option>
                  <option value="1.25" ${sr.speed === 1.25 ? 'selected' : ''}>1.25x</option>
                  <option value="1.5" ${sr.speed === 1.5 ? 'selected' : ''}>1.5x</option>
                  <option value="2.0" ${sr.speed === 2.0 ? 'selected' : ''}>2.0x</option>
                  <option value="3.0" ${sr.speed === 3.0 ? 'selected' : ''}>3.0x</option>
                </select>
                <button style="background:none;border:none;color:#f0524d;cursor:pointer;" data-del-spd="${idx}">✕</button>
              </div>
            `;
          });
        }
        html += `</div></div>`;
        rightContent.innerHTML = html;

        const btnAddSpd = document.getElementById('btn-add-speed');
        if (btnAddSpd) {
          btnAddSpd.addEventListener('click', () => {
            const curClock = scene ? Math.max(0, scene.clock || 0) : 0;
            const duration = scene ? scene.duration || 30 : 30;
            if (!edits.speed_ranges) edits.speed_ranges = [];
            edits.speed_ranges.push({
              start: Math.round(curClock * 10) / 10,
              end: Math.round(Math.min(duration, curClock + 2) * 10) / 10,
              speed: 1.5,
            });
            applyChange();
          });
        }

        rightContent.querySelectorAll('[data-spd-start]').forEach((input) => {
          input.addEventListener('change', () => {
            const idx = Number(input.dataset.spdStart);
            const val = Number(input.value);
            const sr = edits.speed_ranges[idx];
            if (sr && !isNaN(val)) {
              sr.start = Math.max(0, Math.round(val * 10) / 10);
              if (sr.end <= sr.start) {
                sr.end = Math.round((sr.start + 0.5) * 10) / 10;
              }
              applyChange();
            }
          });
        });

        rightContent.querySelectorAll('[data-spd-end]').forEach((input) => {
          input.addEventListener('change', () => {
            const idx = Number(input.dataset.spdEnd);
            const val = Number(input.value);
            const sr = edits.speed_ranges[idx];
            if (sr && !isNaN(val)) {
              sr.end = Math.max(Math.round((sr.start + 0.1) * 10) / 10, Math.round(val * 10) / 10);
              applyChange();
            }
          });
        });

        rightContent.querySelectorAll('[data-spd-idx]').forEach((sel) => {
          sel.addEventListener('change', () => {
            const idx = Number(sel.dataset.spdIdx);
            edits.speed_ranges[idx].speed = Number(sel.value);
            applyChange();
          });
        });

        rightContent.querySelectorAll('[data-del-spd]').forEach((btn) => {
          btn.addEventListener('click', () => {
            const idx = Number(btn.dataset.delSpd);
            edits.speed_ranges.splice(idx, 1);
            applyChange();
          });
        });
      }
    }

    // Timeline Rendering
    function renderTimelineTracks() {
      const trackSubs = document.getElementById('track-subs');
      const trackOv = document.getElementById('track-overlays');
      const trackSpd = document.getElementById('track-speed');
      const duration = scene ? scene.duration || 30 : 30;

      if (trackSubs) {
        const cues = scene && typeof scene.getCues === 'function' ? scene.getCues() : [];
        let html = '<span class="timeline-track-label">3-Word Subtitles</span>';
        cues.forEach((c) => {
          const leftPct = (c.start / duration) * 100;
          const widthPct = Math.max(0.5, ((c.end - c.start) / duration) * 100);
          html += `
            <div class="track-segment sub" style="left:${leftPct}%;width:${widthPct}%;" data-tseek="${c.start}" title="${c.text}">
              ${c.text}
            </div>
          `;
        });
        trackSubs.innerHTML = html;
      }

      if (trackOv) {
        const overlays = edits.media_overlays || [];
        let html = '<span class="timeline-track-label">Media Overlays</span>';
        overlays.forEach((o) => {
          const leftPct = (o.start / duration) * 100;
          const widthPct = Math.max(0.8, ((o.end - o.start) / duration) * 100);
          html += `
            <div class="track-segment ov" style="left:${leftPct}%;width:${widthPct}%;" data-tseek="${o.start}" title="${o.name || o.id}">
              ${o.name || o.id}
            </div>
          `;
        });
        trackOv.innerHTML = html;
      }

      if (trackSpd) {
        const speeds = edits.speed_ranges || [];
        let html = '<span class="timeline-track-label">Speed Ranges</span>';
        speeds.forEach((sr) => {
          const leftPct = (sr.start / duration) * 100;
          const widthPct = Math.max(0.8, ((sr.end - sr.start) / duration) * 100);
          html += `
            <div class="track-segment spd" style="left:${leftPct}%;width:${widthPct}%;" data-tseek="${sr.start}">
              ${sr.speed}x
            </div>
          `;
        });
        trackSpd.innerHTML = html;
      }

      if (timelineTracks) {
        timelineTracks.querySelectorAll('.track-segment[data-tseek]').forEach((el) => {
          el.addEventListener('click', (e) => {
            e.stopPropagation();
            const t = Number(el.dataset.tseek);
            if (scene && typeof scene.seek === 'function') scene.seek(t);
          });
        });
      }
    }

    // Transport playback button
    if (playBtn) {
      playBtn.addEventListener('click', () => {
        if (scene && typeof scene.play === 'function') {
          scene.play();
        }
      });
    }

    // Timeline Scrubbing
    let isScrubbing = false;
    function handleTimelineScrub(e) {
      if (!timelineTracks) return;
      const rect = timelineTracks.getBoundingClientRect();
      const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const duration = scene ? scene.duration || 30 : 30;
      const t = (x / rect.width) * duration;
      if (scene && typeof scene.seek === 'function') {
        scene.seek(t);
      }
    }
    if (timelineTracks) {
      timelineTracks.addEventListener('mousedown', (e) => {
        isScrubbing = true;
        handleTimelineScrub(e);
      });
    }
    window.addEventListener('mousemove', (e) => {
      if (isScrubbing) handleTimelineScrub(e);
    });
    window.addEventListener('mouseup', () => {
      isScrubbing = false;
    });

    // Sync Playhead & Timecode
    function updatePlayhead() {
      const curClock = scene ? scene.clock || 0 : 0;
      const duration = scene ? scene.duration || 30 : 30;
      if (playhead) {
        const pct = (curClock / duration) * 100;
        playhead.style.left = `${pct}%`;
      }
      if (timecodeDisplay) {
        const m1 = Math.floor(curClock / 60);
        const s1 = (curClock % 60).toFixed(2).padStart(5, '0');
        const m2 = Math.floor(duration / 60);
        const s2 = (duration % 60).toFixed(2).padStart(5, '0');
        timecodeDisplay.textContent = `${m1}:${s1} / ${m2}:${s2}`;
      }
      requestAnimationFrame(updatePlayhead);
    }
    requestAnimationFrame(updatePlayhead);

    // On-Stage Pointer Drag & Resize Handling
    let dragTarget = null; // { type: 'subtitles'|'overlay_move'|'overlay_resize', id?: '...', dir?: 'tl'|'tr'|'bl'|'br', startX, startY, startW?, startH?, clientX, clientY }

    if (subtitlesBox) {
      subtitlesBox.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        selectedItem = { type: 'subtitles' };
        activeInspectorTab = 'subtitles';
        stage.querySelectorAll('.media-overlay-item').forEach((item) => item.classList.remove('selected'));
        const sub = edits.subtitles || {};
        dragTarget = {
          type: 'subtitles',
          startX: sub.x != null ? sub.x : 0.5,
          startY: sub.y != null ? sub.y : 0.78,
          clientX: e.clientX,
          clientY: e.clientY,
        };
        renderInspector();
      });
    }

    stage.addEventListener('pointerdown', (e) => {
      const resizeHandle = e.target.closest('[data-resize]');
      const ovEl = e.target.closest('.media-overlay-item');
      if (ovEl) {
        e.stopPropagation();
        const id = ovEl.dataset.id;
        const ov = (edits.media_overlays || []).find((o) => o.id === id);
        selectedItem = { type: 'overlay', id };
        activeInspectorTab = 'overlays';

        stage.querySelectorAll('.media-overlay-item').forEach((item) => {
          item.classList.toggle('selected', item.dataset.id === id);
        });

        if (resizeHandle && ov) {
          dragTarget = {
            type: 'overlay_resize',
            id,
            dir: resizeHandle.dataset.resize, // 'tl' | 'tr' | 'bl' | 'br'
            startX: ov.x != null ? ov.x : 0.5,
            startY: ov.y != null ? ov.y : 0.5,
            startW: ov.width != null ? ov.width : 0.4,
            startH: ov.height != null ? ov.height : 0.3,
            clientX: e.clientX,
            clientY: e.clientY,
          };
        } else if (ov) {
          dragTarget = {
            type: 'overlay_move',
            id,
            startX: ov.x != null ? ov.x : 0.5,
            startY: ov.y != null ? ov.y : 0.5,
            clientX: e.clientX,
            clientY: e.clientY,
          };
        }
        renderInspector();
      }
    });

    window.addEventListener('pointermove', (e) => {
      if (!dragTarget) return;
      const stageRect = stage.getBoundingClientRect();
      const dx = (e.clientX - dragTarget.clientX) / stageRect.width;
      const dy = (e.clientY - dragTarget.clientY) / stageRect.height;

      if (dragTarget.type === 'subtitles') {
        const nextX = Math.max(0.05, Math.min(0.95, dragTarget.startX + dx));
        const nextY = Math.max(0.05, Math.min(0.95, dragTarget.startY + dy));
        edits.subtitles.x = Math.round(nextX * 1000) / 1000;
        edits.subtitles.y = Math.round(nextY * 1000) / 1000;
        if (scene && typeof scene.applyEdits === 'function') {
          scene.applyEdits(edits);
        }
      } else if (dragTarget.type === 'overlay_move') {
        const ov = (edits.media_overlays || []).find((o) => o.id === dragTarget.id);
        if (ov) {
          const nextX = Math.max(0.05, Math.min(0.95, dragTarget.startX + dx));
          const nextY = Math.max(0.05, Math.min(0.95, dragTarget.startY + dy));
          ov.x = Math.round(nextX * 1000) / 1000;
          ov.y = Math.round(nextY * 1000) / 1000;
          if (scene && typeof scene.applyEdits === 'function') {
            scene.applyEdits(edits);
          }
        }
      } else if (dragTarget.type === 'overlay_resize') {
        const ov = (edits.media_overlays || []).find((o) => o.id === dragTarget.id);
        if (ov) {
          let deltaW = 0;
          let deltaH = 0;
          if (dragTarget.dir === 'br') {
            deltaW = dx * 2;
            deltaH = dy * 2;
          } else if (dragTarget.dir === 'bl') {
            deltaW = -dx * 2;
            deltaH = dy * 2;
          } else if (dragTarget.dir === 'tr') {
            deltaW = dx * 2;
            deltaH = -dy * 2;
          } else if (dragTarget.dir === 'tl') {
            deltaW = -dx * 2;
            deltaH = -dy * 2;
          }
          const nextW = Math.max(0.05, Math.min(1.0, dragTarget.startW + deltaW));
          const nextH = Math.max(0.05, Math.min(1.0, dragTarget.startH + deltaH));
          ov.width = Math.round(nextW * 1000) / 1000;
          ov.height = Math.round(nextH * 1000) / 1000;
          if (scene && typeof scene.applyEdits === 'function') {
            scene.applyEdits(edits);
          }
        }
      }
    });

    window.addEventListener('pointerup', () => {
      if (dragTarget) {
        dragTarget = null;
        applyChange(true);
      }
    });

    function renderAll() {
      updateHeaderButtons();
      renderLeftPanel();
      renderInspector();
      renderTimelineTracks();
    }

    loadAssets();
    renderAll();
  }

  // Hook for engine.js to initialize editor
  g.__initEditor = initStudio;
})();
