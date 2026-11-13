from pathlib import Path
import subprocess
import json
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_default_edits_schema_in_engine_and_editor():
    engine_code = (ROOT / "template" / "engine.js").read_text(encoding="utf-8")
    assert "deleted_ranges" in engine_code

    node_script = """
    const fs = require('fs');
    const engineCode = fs.readFileSync('template/engine.js', 'utf8');

    // Run in minimal mock to check scene default edits schema
    globalThis.window = globalThis;
    globalThis.innerWidth = 1920;
    globalThis.innerHeight = 1080;
    globalThis.location = { search: '?still' };
    const makeEl = () => ({
      style: {},
      classList: { add(){}, toggle(){} },
      dataset: {},
      children: [],
      setAttribute(){},
      removeAttribute(){},
      querySelector: () => null,
      querySelectorAll: () => [],
      appendChild: () => ({})
    });
    globalThis.document = {
      body: makeEl(),
      querySelector: () => makeEl(),
      querySelectorAll: () => [],
      createElement: () => makeEl(),
      addEventListener: () => {}
    };
    globalThis.addEventListener = () => {};
    globalThis.requestAnimationFrame = () => {};
    globalThis.performance = { now: () => 1000 };
    globalThis.DEMO_PROGRAM = { duration: 10, fps: 30, words: [], chapters: [] };
    globalThis.gsap = { timeline: () => ({ seek(){}, duration: () => 10, set(){} }) };
    globalThis.buildScene = () => {};
    globalThis.fetch = async () => ({ ok: false });

    eval(engineCode);

    setTimeout(() => {
      const edits = window.__scene.getEdits();
      if (!Array.isArray(edits.deleted_ranges)) {
        throw new Error('deleted_ranges missing or not array');
      }
      console.log('SCHEMA_OK');
    }, 50);
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "SCHEMA_OK" in proc.stdout


def test_editor_code_and_css_presence():
    editor_js = (ROOT / "template" / "editor.js").read_text(encoding="utf-8")
    editor_css = (ROOT / "template" / "editor.css").read_text(encoding="utf-8")

    # 1. Top bar buttons
    assert "btn-safe-zone" in editor_js
    assert "btn-rebuild" in editor_js
    assert "btn-export" in editor_js

    # 2. Safe zone elements & css
    assert "safe-zone-guide" in editor_js
    assert "safe-zone-right" in editor_js
    assert "safe-zone-bottom" in editor_js
    assert "#safe-zone-guide" in editor_css
    assert ".still-mode #safe-zone-guide" in editor_css
    assert "display: none !important" in editor_css

    # 3. Source Footage upload & auto-cut init in Left Panel
    assert "src-file-input" in editor_js
    assert "btn-upload-src" in editor_js
    assert "btn-init-project" in editor_js
    assert "/api/source-video" in editor_js
    assert "/api/init-project" in editor_js

    # 4. Audio inspector & Subtitle cut buttons
    assert 'data-tab="audio"' in editor_js or 'data-itab="audio"' in editor_js
    assert "data-del-aud" in editor_js
    assert "data-aud-seek" in editor_js
    assert "data-aud-start" in editor_js
    assert "data-aud-end" in editor_js
    assert "data-aud-trim" in editor_js
    assert "data-aud-gain" in editor_js
    assert "data-cut-cue" in editor_js
    assert "data-restore-del" in editor_js

    # 5. Timeline 4th track and segment handles
    assert "track-audio" in editor_js
    assert "seg-handle left" in editor_js or "seg-handle.left" in editor_js or ('seg-handle' in editor_js and 'left' in editor_js)
    assert "data-seg-handle" in editor_js
    assert "data-seg-kind" in editor_js
    assert ".seg-handle" in editor_css
    assert "#track-audio" in editor_css


def test_editor_js_dom_interactions_in_node():
    node_script = """
    const fs = require('fs');
    const editorCode = fs.readFileSync('template/editor.js', 'utf8');

    class MockClassList {
      constructor() { this.classes = new Set(); }
      add(c) { this.classes.add(c); }
      remove(c) { this.classes.delete(c); }
      contains(c) { return this.classes.has(c); }
      toggle(c, force) {
        if (typeof force === 'boolean') {
          if (force) this.classes.add(c); else this.classes.delete(c);
        } else {
          if (this.classes.has(c)) this.classes.delete(c); else this.classes.add(c);
        }
        return this.classes.has(c);
      }
    }

    class MockElement {
      constructor(tagName) {
        this.tagName = (tagName || 'DIV').toUpperCase();
        this.style = {};
        this.dataset = {};
        this.children = [];
        this.classList = new MockClassList();
        this.listeners = {};
        this._innerHTML = '';
        this.value = '';
        this.checked = false;
        this.id = '';
      }
      get className() { return Array.from(this.classList.classes).join(' '); }
      set className(val) {
        this.classList.classes.clear();
        (val || '').split(/\\s+/).filter(Boolean).forEach(c => this.classList.classes.add(c));
      }
      get innerHTML() { return this._innerHTML; }
      set innerHTML(val) {
        this._innerHTML = val;
        this.children = [];
        this._parseMockChildren(val);
      }
      get textContent() { return this._innerHTML.replace(/<[^>]+>/g, ''); }
      set textContent(v) { this._innerHTML = v; }
      setAttribute(k, v) { this[k] = v; }
      getAttribute(k) { return this[k]; }
      removeAttribute(k) { delete this[k]; }
      appendChild(child) { this.children.push(child); child.parentElement = this; return child; }
      removeChild(child) {
        const i = this.children.indexOf(child);
        if (i !== -1) this.children.splice(i, 1);
        child.parentElement = null;
        return child;
      }
      addEventListener(type, cb) {
        if (!this.listeners[type]) this.listeners[type] = [];
        this.listeners[type].push(cb);
      }
      dispatchEvent(event) {
        const list = this.listeners[event.type] || [];
        for (const cb of list) cb(event);
      }
      click() {
        this.dispatchEvent({ type: 'click', target: this, stopPropagation(){} });
      }
      closest(sel) {
        let cur = this;
        while (cur) {
          if (cur._matches(sel)) return cur;
          cur = cur.parentElement;
        }
        return null;
      }
      _matches(sel) {
        if (sel.includes('[') && sel.startsWith('.')) {
          const [cls, attrPart] = sel.split('[');
          const className = cls.slice(1);
          if (!this.classList.contains(className)) return false;
          sel = '[' + attrPart;
        }
        if (sel.startsWith('#')) return this.id === sel.slice(1);
        if (sel.startsWith('.')) return this.classList.contains(sel.slice(1));
        if (sel.startsWith('[data-')) {
          const match = sel.match(/\\[([\\w-]+)(?:="([^"]*)")?\\]/);
          if (match) {
            const attr = match[1].replace('data-', '').replace(/-([a-z])/g, (_, l) => l.toUpperCase());
            if (match[2] !== undefined) return this.dataset[attr] === match[2];
            return this.dataset[attr] !== undefined;
          }
        }
        return this.tagName.toLowerCase() === sel.toLowerCase();
      }
      querySelector(sel) {
        return this._findAll(sel)[0] || null;
      }
      querySelectorAll(sel) {
        return this._findAll(sel);
      }
      _findAll(sel) {
        const res = [];
        for (const c of this.children) {
          if (c._matches(sel)) res.push(c);
          res.push(...c._findAll(sel));
        }
        return res;
      }
      _parseMockChildren(html) {
        // Minimal mock parser to extract elements with id or class or data-*
        const tagRegex = /<([a-zA-Z0-9]+)([^>]*)>([\\s\\S]*?)<\\/\\1>|<([a-zA-Z0-9]+)([^>]*)\\/>/g;
        let match;
        while ((match = tagRegex.exec(html)) !== null) {
          const tagName = match[1] || match[4];
          const attrStr = match[2] || match[5] || '';
          const inner = match[3] || '';
          const el = new MockElement(tagName);
          el.parentElement = this;

          // Parse id
          const idMatch = attrStr.match(/id="([^"]+)"/);
          if (idMatch) el.id = idMatch[1];

          // Parse class
          const clsMatch = attrStr.match(/class="([^"]+)"/);
          if (clsMatch) el.className = clsMatch[1];

          // Parse data attributes
          const dataRegex = /data-([a-zA-Z0-9\\-]+)="([^"]*)"/g;
          let dMatch;
          while ((dMatch = dataRegex.exec(attrStr)) !== null) {
            const camelKey = dMatch[1].replace(/-([a-z])/g, (_, l) => l.toUpperCase());
            el.dataset[camelKey] = dMatch[2];
          }

          if (inner && !inner.includes('<')) {
            el.textContent = inner.trim();
          } else if (inner) {
            el.innerHTML = inner;
          }
          this.children.push(el);
        }
      }
    }

    const stageEl = new MockElement('DIV');
    stageEl.id = 'stage';
    const editorUi = new MockElement('DIV');
    editorUi.id = 'editor-ui';
    const subsBox = new MockElement('DIV');
    subsBox.id = 'subtitles-box';

    const elementsById = {
      'stage': stageEl,
      'editor-ui': editorUi,
      'subtitles-box': subsBox
    };

    globalThis.window = globalThis;
    globalThis.addEventListener = () => {};
    globalThis.document = {
      body: new MockElement('BODY'),
      getElementById: (id) => elementsById[id] || editorUi.querySelector('#' + id) || stageEl.querySelector('#' + id) || null,
      querySelector: (sel) => {
        if (sel.startsWith('#')) {
          const id = sel.slice(1);
          return elementsById[id] || editorUi.querySelector(sel) || stageEl.querySelector(sel) || null;
        }
        return null;
      },
      querySelectorAll: () => [],
      createElement: (tag) => new MockElement(tag),
      addEventListener: () => {}
    };
    globalThis.location = { search: '', reload: () => {} };
    globalThis.fetch = async (url, opts) => ({
      ok: true,
      json: async () => ({ ok: true, assets: [], sfx: [] })
    });
    globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 16);

    eval(editorCode);

    let lastAppliedEdits = null;
    const sceneMock = {
      clock: 1.0,
      duration: 30.0,
      applyEdits: (next) => { lastAppliedEdits = next; },
      seek: () => {},
      play: () => {},
      getCues: () => [
        { id: 'sub_0', start: 0.0, end: 1.0, text: 'Hello world test' },
        { id: 'sub_1', start: 1.2, end: 2.2, text: 'Cut this phrase' }
      ]
    };

    const initialEdits = {
      version: 1,
      aspect: '9:16',
      stage: { width: 1080, height: 1920 },
      subtitles: { enabled: true, overrides: {} },
      speed_ranges: [],
      deleted_ranges: [],
      media_overlays: [],
      audio_clips: [
        { id: 'aud-1', type: 'audio', name: 'music.mp3', src: 'assets/music.mp3', url: '../assets/music.mp3', start: 0.5, end: 4.5, trim_start: 0.0, gain_db: -3.0 }
      ]
    };

    window.__initEditor(sceneMock, initialEdits);

    // 1. Verify Top Bar buttons exist
    const btnSafeZone = editorUi.querySelector('#btn-safe-zone');
    const btnRebuild = editorUi.querySelector('#btn-rebuild');
    const btnExport = editorUi.querySelector('#btn-export');
    if (!btnSafeZone) throw new Error('#btn-safe-zone missing');
    if (!btnRebuild) throw new Error('#btn-rebuild missing');
    if (!btnExport) throw new Error('#btn-export missing');

    // 2. Safe zone guide injected inside #stage
    const safeZoneGuide = stageEl.querySelector('#safe-zone-guide');
    if (!safeZoneGuide) throw new Error('#safe-zone-guide missing inside #stage');
    btnSafeZone.click();
    if (!safeZoneGuide.classList.contains('active') || !btnSafeZone.classList.contains('active')) {
      throw new Error('#btn-safe-zone click did not toggle active class');
    }

    // 3. 4th timeline track #track-audio
    const trackAudio = editorUi.querySelector('#track-audio');
    if (!trackAudio) throw new Error('#track-audio missing');

    // 4. Source video upload & init project buttons
    const srcInput = editorUi.querySelector('#src-file-input');
    const btnUploadSrc = editorUi.querySelector('#btn-upload-src');
    const btnInit = editorUi.querySelector('#btn-init-project');
    if (!srcInput) throw new Error('#src-file-input missing');
    if (!btnUploadSrc) throw new Error('#btn-upload-src missing');
    if (!btnInit) throw new Error('#btn-init-project missing');

    // 5. Right Inspector Audio tab
    const audioTab = editorUi.querySelector('.panel-tab[data-itab="audio"]') || editorUi.querySelector('.panel-tab[data-tab="audio"]');
    if (!audioTab) throw new Error('Audio inspector tab button missing');

    // 6. Subtitle cut button & restore
    const cutBtn = editorUi.querySelector('[data-cut-cue="sub_1"]');
    if (!cutBtn) throw new Error('data-cut-cue="sub_1" missing in subtitles tab');
    cutBtn.click();
    if (!lastAppliedEdits || !lastAppliedEdits.deleted_ranges.length || lastAppliedEdits.deleted_ranges[0].text !== 'Cut this phrase') {
      throw new Error('Clicking cue-cut-btn did not append to deleted_ranges: ' + JSON.stringify(lastAppliedEdits && lastAppliedEdits.deleted_ranges));
    }

    const restoreBtn = editorUi.querySelector('[data-restore-del]');
    if (!restoreBtn) throw new Error('data-restore-del missing after adding deleted cut');
    restoreBtn.click();
    if (!lastAppliedEdits || lastAppliedEdits.deleted_ranges.length !== 0) {
      throw new Error('Clicking restoreBtn did not remove deleted range');
    }

    // 7. Audio tab switch and inspector controls
    audioTab.click();
    const rightContent = document.getElementById('right-panel-content');
    if (!rightContent || !rightContent.innerHTML.includes('data-aud-gain="aud-1"')) {
      throw new Error('[data-aud-gain="aud-1"] missing in audio tab HTML: ' + (rightContent ? rightContent.innerHTML : 'no rightContent'));
    }
    if (!rightContent.innerHTML.includes('data-del-aud="aud-1"')) {
      throw new Error('[data-del-aud="aud-1"] missing in audio tab HTML');
    }

    // 8. Track segment handles on #track-audio
    if (!trackAudio.innerHTML.includes('data-seg-handle="left"') || !trackAudio.innerHTML.includes('data-seg-handle="right"')) {
      throw new Error('Segment handles missing on audio segment in #track-audio: ' + trackAudio.innerHTML);
    }

    console.log('EDITOR_DOM_OK');
    process.exit(0);
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "EDITOR_DOM_OK" in proc.stdout


def test_engine_js_deleted_ranges_and_custom_audio_in_node():
    node_script = """
    const fs = require('fs');
    const engineCode = fs.readFileSync('template/engine.js', 'utf8');

    class MockClassList {
      constructor() { this.classes = new Set(); }
      add(c) { this.classes.add(c); }
      remove(c) { this.classes.delete(c); }
      contains(c) { return this.classes.has(c); }
      toggle(c, v) { if (v) this.classes.add(c); else this.classes.delete(c); }
    }

    class MockElement {
      constructor(tagName) {
        this.tagName = (tagName || 'DIV').toUpperCase();
        this.style = {};
        this.dataset = {};
        this.children = [];
        this.classList = new MockClassList();
        this.textContent = '';
      }
      appendChild(c) { this.children.push(c); return c; }
      removeChild(c) {
        const i = this.children.indexOf(c);
        if (i !== -1) this.children.splice(i, 1);
        return c;
      }
      setAttribute(k, v) { this[k] = v; }
      removeAttribute(k) { delete this[k]; }
      querySelector(sel) {
        if (sel === '.sub-text') return this._subText || (this._subText = new MockElement('SPAN'));
        return null;
      }
      querySelectorAll() { return []; }
    }

    const bodyEl = new MockElement('BODY');
    const stageEl = new MockElement('DIV');
    const videoEl = new MockElement('VIDEO');
    const subtitlesBox = new MockElement('DIV');
    const overlaysLayer = new MockElement('DIV');
    const hudEl = new MockElement('DIV');

    const elementsById = {
      'stage': stageEl,
      'v': videoEl,
      'subtitles-box': subtitlesBox,
      'overlays-layer': overlaysLayer,
      'hud': hudEl
    };

    globalThis.window = globalThis;
    globalThis.innerWidth = 1920;
    globalThis.innerHeight = 1080;
    globalThis.location = { search: '' };
    globalThis.document = {
      body: bodyEl,
      querySelector: (sel) => sel.startsWith('#') ? elementsById[sel.slice(1)] : null,
      querySelectorAll: () => [],
      createElement: (tag) => new MockElement(tag),
      addEventListener: () => {}
    };
    globalThis.addEventListener = () => {};
    globalThis.requestAnimationFrame = () => {};
    globalThis.performance = { now: () => 1000 };
    globalThis.gsap = {
      timeline: () => ({ seek() {}, duration: () => 30, set() {} })
    };
    globalThis.DEMO_PROGRAM = {
      duration: 30,
      fps: 30,
      words: [
        [0.0, 0.5, 'Hello'],
        [1.0, 1.8, 'Skipped'],
        [2.5, 3.0, 'Keep']
      ],
      chapters: []
    };
    globalThis.chunkThreeWords = () => [
      { id: 'sub_0', start: 0.0, end: 0.5, text: 'Hello' },
      { id: 'sub_1', start: 1.0, end: 1.8, text: 'Skipped' },
      { id: 'sub_2', start: 2.5, end: 3.0, text: 'Keep' }
    ];
    globalThis.buildScene = () => {};
    globalThis.fetch = async () => ({ ok: false });

    // Mock WebAudio AudioContext
    class MockGain {
      constructor() { this.gain = { value: 1 }; }
      connect() { return this; }
    }
    class MockSource {
      constructor() {
        this.buffer = null;
        this.started = false;
        this.startParams = null;
      }
      connect() { return this; }
      start(...args) {
        this.started = true;
        this.startParams = args;
      }
    }
    class MockAudioContext {
      constructor() { this.state = 'running'; this.destination = {}; }
      createGain() { return new MockGain(); }
      createBufferSource() { return new MockSource(); }
      async decodeAudioData() { return { duration: 5 }; }
    }
    globalThis.AudioContext = MockAudioContext;

    eval(engineCode);

    setTimeout(() => {
      const scene = window.__scene;
      if (!scene) throw new Error('window.__scene not initialized');

      const edits = scene.getEdits();
      if (!Array.isArray(edits.deleted_ranges)) {
        throw new Error('deleted_ranges missing in scene.getEdits()');
      }

      // Add a deleted range [1.0, 2.0] and an audio clip
      scene.applyEdits({
        ...edits,
        deleted_ranges: [
          { id: 'del-1', start: 1.0, end: 2.0, text: 'Skipped' }
        ],
        audio_clips: [
          { id: 'aud-1', type: 'audio', name: 'track.mp3', src: 'assets/track.mp3', url: '../assets/track.mp3', start: 0.5, end: 4.5, trim_start: 1.0, gain_db: -6.0 }
        ]
      });

      // At t = 1.5 (inside deleted range), subtitlesBox should be hidden / display none
      scene.render(1.5).then(() => {
        if (subtitlesBox.style.display !== 'none' && subtitlesBox.style.visibility !== 'hidden') {
          throw new Error('subtitlesBox was not hidden during deleted range t=1.5');
        }
        console.log('ENGINE_OK');
        process.exit(0);
      });
    }, 50);
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ENGINE_OK" in proc.stdout
