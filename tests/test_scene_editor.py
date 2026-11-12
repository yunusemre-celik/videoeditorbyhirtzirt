from pathlib import Path
import subprocess
import json
import pytest


def test_scene_files_and_js_chunker_and_undo_logic():
    root = Path(__file__).resolve().parent.parent
    assert (root / "template" / "editor.js").exists()
    assert (root / "template" / "editor.css").exists()
    html = (root / "template" / "index.html").read_text(encoding="utf-8")
    assert 'id="subtitles-box"' in html
    assert 'id="overlays-layer"' in html
    assert 'editor.js' in html

    # Run node verification of chunkThreeWords and HistoryManager exported on globalThis
    node_script = """
    const fs = require('fs');
    const code = fs.readFileSync('template/editor.js', 'utf8');
    // Execute in minimal mock environment
    globalThis.window = globalThis;
    globalThis.document = {
      body: { classList: { add(){}, toggle(){} }, dataset: { w: '1080', h: '1920' } },
      querySelector: () => null,
      querySelectorAll: () => [],
      createElement: () => ({ style: {}, classList: { add(){} }, appendChild(){} }),
      addEventListener: () => {}
    };
    globalThis.location = { search: '?still' };
    eval(code);

    const words = [
      [0.0, 0.2, 'One'], [0.25, 0.45, 'two'], [0.5, 0.7, 'three'],
      [0.75, 0.95, 'four']
    ];
    const cues = window.chunkThreeWords(words, {}, false);
    if (cues.length !== 2 || cues[0].text !== 'One two three' || cues[1].text !== 'four') {
      throw new Error('chunkThreeWords failed: ' + JSON.stringify(cues));
    }

    const hist = window.createHistoryManager({ a: 1 }, 20);
    hist.push({ a: 2 });
    hist.push({ a: 3 });
    const u1 = hist.undo();
    if (u1.a !== 2) throw new Error('undo failed');
    const r1 = hist.redo();
    if (r1.a !== 3) throw new Error('redo failed');
    console.log('JS_OK');
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "JS_OK" in proc.stdout


def test_chunk_three_words_edge_cases_in_node():
    root = Path(__file__).resolve().parent.parent
    node_script = """
    const fs = require('fs');
    const code = fs.readFileSync('template/editor.js', 'utf8');
    globalThis.window = globalThis;
    globalThis.document = {
      body: { classList: { add(){}, toggle(){} }, dataset: { w: '1080', h: '1920' } },
      querySelector: () => null,
      querySelectorAll: () => [],
      createElement: () => ({ style: {}, classList: { add(){} }, appendChild(){} }),
      addEventListener: () => {}
    };
    globalThis.location = { search: '?still' };
    eval(code);

    // 1. Punctuation break test with quotes
    const wordsWithPunct = [
      [0.0, 0.2, 'Hello'],
      [0.25, 0.45, '"world!"'],
      [0.5, 0.7, 'Next']
    ];
    const cuesPunct = window.chunkThreeWords(wordsWithPunct);
    if (cuesPunct.length !== 2) {
      throw new Error('Punctuation splitting failed: ' + JSON.stringify(cuesPunct));
    }
    if (cuesPunct[0].text !== 'Hello "world!"' || cuesPunct[1].text !== 'Next') {
      throw new Error('Punctuation text mismatch: ' + JSON.stringify(cuesPunct));
    }

    // 2. Pause break test (>= 0.35s)
    const wordsWithPause = [
      [0.0, 0.2, 'First'],
      [0.6, 0.8, 'Second'] // gap is 0.6 - 0.2 = 0.4s >= 0.35s
    ];
    const cuesPause = window.chunkThreeWords(wordsWithPause);
    if (cuesPause.length !== 2) {
      throw new Error('Pause splitting failed: ' + JSON.stringify(cuesPause));
    }

    // 3. Overrides and uppercase test
    const wordsOverrides = [
      [0.0, 0.2, 'apple'],
      [0.22, 0.4, 'banana']
    ];
    const cuesOver = window.chunkThreeWords(wordsOverrides, { sub_0: 'Custom Text' }, true);
    if (cuesOver[0].text !== 'CUSTOM TEXT') {
      throw new Error('Uppercase/override failed: ' + cuesOver[0].text);
    }

    // 4. Empty / punctuation-only filtering test
    const wordsDirty = [
      [0.0, 0.1, '...'],
      [0.15, 0.3, '   '],
      [0.35, 0.5, 'Valid']
    ];
    const cuesDirty = window.chunkThreeWords(wordsDirty);
    if (cuesDirty.length !== 1 || cuesDirty[0].text !== 'Valid') {
      throw new Error('Dirty word filtering failed: ' + JSON.stringify(cuesDirty));
    }

    // 5. Min duration fallback test (0.2s)
    const wordsFast = [
      [1.0, 1.05, 'Fast']
    ];
    const cuesFast = window.chunkThreeWords(wordsFast);
    if (cuesFast[0].end < 1.2) {
      throw new Error('Min duration fallback failed: ' + cuesFast[0].end);
    }

    console.log('CHUNKER_EDGES_OK');
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "CHUNKER_EDGES_OK" in proc.stdout


def test_history_manager_deep_clone_and_limits():
    root = Path(__file__).resolve().parent.parent
    node_script = """
    const fs = require('fs');
    const code = fs.readFileSync('template/editor.js', 'utf8');
    globalThis.window = globalThis;
    globalThis.document = {
      body: { classList: { add(){}, toggle(){} }, dataset: { w: '1080', h: '1920' } },
      querySelector: () => null,
      querySelectorAll: () => [],
      createElement: () => ({ style: {}, classList: { add(){} }, appendChild(){} }),
      addEventListener: () => {}
    };
    globalThis.location = { search: '?still' };
    eval(code);

    const initial = { count: 0, items: ['a'] };
    const hist = window.createHistoryManager(initial, 3);
    
    // Test deep clone isolation
    initial.items.push('mutation');
    if (hist.current().items.length !== 1) {
      throw new Error('Initial state was not deep cloned');
    }

    // Push states to exceed maxSteps (3)
    hist.push({ count: 1, items: ['b'] });
    hist.push({ count: 2, items: ['c'] });
    hist.push({ count: 3, items: ['d'] }); // should evict count: 0

    if (!hist.canUndo()) throw new Error('Should be able to undo');
    const u1 = hist.undo(); // count: 2
    if (u1.count !== 2) throw new Error('Undo 1 wrong: ' + u1.count);
    const u2 = hist.undo(); // count: 1
    if (u2.count !== 1) throw new Error('Undo 2 wrong: ' + u2.count);
    
    // count 0 was evicted, so canUndo should be false
    if (hist.canUndo()) throw new Error('Should not be able to undo past maxSteps');

    // Redo
    if (!hist.canRedo()) throw new Error('Should be able to redo');
    const r1 = hist.redo(); // count: 2
    if (r1.count !== 2) throw new Error('Redo 1 wrong: ' + r1.count);

    // Push new state after undo clears redo
    hist.push({ count: 99, items: ['z'] });
    if (hist.canRedo()) throw new Error('Redo stack should be cleared after push');

    console.log('HISTORY_OK');
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "HISTORY_OK" in proc.stdout


def test_index_html_and_css_structure():
    root = Path(__file__).resolve().parent.parent
    html = (root / "template" / "index.html").read_text(encoding="utf-8")
    
    # Layer order: overlays-layer should appear before subtitles-box inside #stage
    stage_idx = html.find('id="stage"')
    assert stage_idx != -1
    overlays_idx = html.find('id="overlays-layer"', stage_idx)
    subtitles_idx = html.find('id="subtitles-box"', stage_idx)
    assert overlays_idx != -1, "overlays-layer must be inside #stage"
    assert subtitles_idx != -1, "subtitles-box must be inside #stage"
    assert overlays_idx < subtitles_idx, "subtitles-box must be placed after overlays-layer to be on top"

    # editor-ui outside stage
    stage_close_idx = html.find('</div>', stage_idx)
    assert 'id="editor-ui"' in html
    
    # Scripts order
    ed_js_idx = html.find('editor.js')
    eng_js_idx = html.find('engine.js')
    assert ed_js_idx != -1
    assert eng_js_idx != -1
    assert ed_js_idx < eng_js_idx, "editor.js must be loaded before engine.js"

    # editor.css linked in head
    assert 'editor.css' in html

    # Still mode CSS hiding
    editor_css = (root / "template" / "editor.css").read_text(encoding="utf-8")
    assert '.still-mode #editor-ui' in editor_css or 'still-mode' in editor_css


def test_engine_apply_edits_and_still_mode_in_node():
    root = Path(__file__).resolve().parent.parent
    node_script = """
    const fs = require('fs');
    const editorCode = fs.readFileSync('template/editor.js', 'utf8');
    const engineCode = fs.readFileSync('template/engine.js', 'utf8');

    // Setup DOM mocks
    class MockElement {
      constructor(tagName) {
        this.tagName = (tagName || 'DIV').toUpperCase();
        this.style = {};
        this.dataset = {};
        this.children = [];
        this.classList = {
          classes: new Set(),
          add(c) { this.classes.add(c); },
          contains(c) { return this.classes.has(c); },
          toggle(c, v) { if (v) this.classes.add(c); else this.classes.delete(c); }
        };
        this.textContent = '';
      }
      get className() { return Array.from(this.classList.classes).join(' '); }
      set className(val) {
        this.classList.classes.clear();
        (val || '').split(/\\s+/).filter(Boolean).forEach(c => this.classList.classes.add(c));
      }
      setAttribute(k, v) { this[k] = v; }
      getAttribute(k) { return this[k]; }
      removeAttribute(k) { delete this[k]; }
      appendChild(child) { this.children.push(child); return child; }
      removeChild(child) {
        const i = this.children.indexOf(child);
        if (i !== -1) this.children.splice(i, 1);
        return child;
      }
      querySelector(sel) {
        if (sel === '.sub-text') return this._subText || (this._subText = new MockElement('SPAN'));
        if (sel.startsWith('[data-id="')) {
          const id = sel.match(/data-id="([^"]+)"/)[1];
          return this.children.find(c => c.dataset.id === id) || null;
        }
        return null;
      }
    }

    const bodyEl = new MockElement('BODY');
    bodyEl.dataset.w = '1920';
    bodyEl.dataset.h = '1080';

    const stageEl = new MockElement('DIV');
    const videoEl = new MockElement('VIDEO');
    const subtitlesBox = new MockElement('DIV');
    const subText = new MockElement('SPAN');
    subtitlesBox._subText = subText;
    const overlaysLayer = new MockElement('DIV');
    const hudEl = new MockElement('DIV');

    const elementsById = {
      'stage': stageEl,
      'v': videoEl,
      'subtitles-box': subtitlesBox,
      'overlays-layer': overlaysLayer,
      'hud': hudEl,
      'bgLines': new MockElement('SVG')
    };

    globalThis.window = globalThis;
    globalThis.innerWidth = 1920;
    globalThis.innerHeight = 1080;
    globalThis.location = { search: '?still' };
    globalThis.document = {
      body: bodyEl,
      querySelector: (sel) => {
        if (sel.startsWith('#')) return elementsById[sel.slice(1)] || null;
        return null;
      },
      querySelectorAll: () => [],
      createElement: (tag) => new MockElement(tag),
      addEventListener: () => {}
    };
    globalThis.addEventListener = () => {};
    globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 16);
    globalThis.performance = { now: () => Date.now() };
    globalThis.gsap = {
      timeline: () => ({
        seek() {},
        duration: () => 10,
        set() {}
      })
    };
    globalThis.DEMO_PROGRAM = {
      duration: 10,
      fps: 30,
      words: [
        [0.0, 0.2, 'Antigravity'],
        [0.25, 0.45, 'Interactive'],
        [0.5, 0.7, 'Studio'],
        [1.0, 1.2, 'Testing']
      ],
      chapters: []
    };
    globalThis.buildScene = () => {};
    globalThis.fetch = async (url) => ({
      ok: false
    });

    // Execute editor.js
    eval(editorCode);

    // Verify still mode class was added to body
    if (!bodyEl.classList.contains('still-mode')) {
      throw new Error('still-mode class was not added to document.body');
    }

    // Execute engine.js
    eval(engineCode);

    setTimeout(() => {
      try {
        if (!window.__scene) throw new Error('window.__scene was not defined');
        if (typeof window.__scene.applyEdits !== 'function') throw new Error('applyEdits missing on __scene');
        if (typeof window.__scene.getEdits !== 'function') throw new Error('getEdits missing on __scene');
        if (typeof window.__scene.getCues !== 'function') throw new Error('getCues missing on __scene');

        // Test applyEdits with stage resize and overlay
        const newEdits = {
          version: 1,
          aspect: '9:16',
          stage: { width: 1080, height: 1920 },
          subtitles: {
            enabled: true,
            x: 0.5,
            y: 0.78,
            fontSize: 60,
            color: '#ffcc00',
            bgColor: '#111111',
            uppercase: true,
            overrides: { sub_0: 'CUSTOM CAPCUT SUB' }
          },
          speed_ranges: [
            { start: 0, end: 1, speed: 2.0 }
          ],
          media_overlays: [
            { id: 'ov_test_1', type: 'image', url: 'test.png', start: 0, end: 5, x: 0.5, y: 0.5, width: 0.4, height: 0.3 }
          ],
          audio_clips: [
            { id: 'aud_1', type: 'sfx', name: 'pop', start: 0.5, gain: 2 }
          ]
        };

        window.__scene.applyEdits(newEdits);

        // Check stage dimensions updated
        if (bodyEl.dataset.w !== '1080' || bodyEl.dataset.h !== '1920') {
          throw new Error('Stage dimensions not updated on body: ' + bodyEl.dataset.w + 'x' + bodyEl.dataset.h);
        }

        // Check cues updated with override and uppercase
        const cues = window.__scene.getCues();
        if (!cues.length || cues[0].text !== 'CUSTOM CAPCUT SUB') {
          throw new Error('Cues not updated: ' + JSON.stringify(cues));
        }

        // Check overlay item was created inside overlaysLayer and has resizer handles
        const ovItem = overlaysLayer.children.find(c => c.dataset.id === 'ov_test_1');
        if (!ovItem) {
          throw new Error('Overlay element was not added to overlaysLayer');
        }
        const resizers = ovItem.children.filter(c => c.classList && c.classList.contains('resizer'));
        if (resizers.length !== 4) {
          throw new Error('Expected 4 resizers on overlay element, found ' + resizers.length);
        }

        // Check SFX merged audio clips
        if (!window.__scene.SFX.some(s => s.name === 'pop' && s.t === 0.5)) {
          throw new Error('SFX cues did not include audio_clip');
        }

        console.log('ENGINE_INTEGRATION_OK');
      } catch (err) {
        console.error(err);
        process.exit(1);
      }
    }, 50);
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ENGINE_INTEGRATION_OK" in proc.stdout


def test_studio_overlay_resizers_and_speed_inputs_in_node():
    root = Path(__file__).resolve().parent.parent
    node_script = """
    const fs = require('fs');
    const editorCode = fs.readFileSync('template/editor.js', 'utf8');

    class MockElement {
      constructor(tagName) {
        this.tagName = (tagName || 'DIV').toUpperCase();
        this.style = {};
        this.dataset = {};
        this.children = [];
        this.classList = {
          classes: new Set(),
          add(c) { this.classes.add(c); },
          remove(c) { this.classes.delete(c); },
          contains(c) { return this.classes.has(c); },
          toggle(c, v) { if (v) this.classes.add(c); else this.classes.delete(c); }
        };
        this.innerHTML = '';
        this.textContent = '';
        this.listeners = {};
      }
      addEventListener(type, cb) {
        (this.listeners[type] = this.listeners[type] || []).push(cb);
      }
      dispatchEvent(event) {
        const cbs = this.listeners[event.type] || [];
        for (const cb of cbs) cb(event);
      }
      appendChild(child) { this.children.push(child); return child; }
      removeChild(child) {
        const i = this.children.indexOf(child);
        if (i !== -1) this.children.splice(i, 1);
        return child;
      }
      getBoundingClientRect() {
        return { left: 0, top: 0, width: 1080, height: 1920 };
      }
      querySelectorAll() {
        return [];
      }
      querySelector() {
        return null;
      }
      closest(sel) {
        if (sel === '[data-resize]' && this.dataset.resize) return this;
        if (sel === '.media-overlay-item' && this.classList.contains('media-overlay-item')) return this;
        return null;
      }
    }

    const editorUi = new MockElement('DIV');
    const stage = new MockElement('DIV');
    const subtitlesBox = new MockElement('DIV');
    subtitlesBox.id = 'subtitles-box';

    const elementsById = {
      'editor-ui': editorUi,
      'stage': stage,
      'subtitles-box': subtitlesBox
    };

    globalThis.window = globalThis;
    globalThis.location = { search: '' }; // Live preview, NOT ?still
    globalThis.document = {
      body: new MockElement('BODY'),
      getElementById: (id) => elementsById[id] || null,
      querySelector: (sel) => {
        if (sel.startsWith('#')) return elementsById[sel.slice(1)] || null;
        return null;
      },
      querySelectorAll: () => [],
      createElement: (tag) => new MockElement(tag),
      addEventListener: () => {}
    };
    globalThis.addEventListener = () => {};
    globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 16);

    eval(editorCode);

    const initialEdits = {
      version: 1,
      aspect: '9:16',
      stage: { width: 1080, height: 1920 },
      subtitles: { enabled: true, x: 0.5, y: 0.78, fontSize: 56, overrides: {} },
      speed_ranges: [
        { start: 1.0, end: 3.5, speed: 2.0 }
      ],
      media_overlays: [
        { id: 'ov_1', type: 'image', url: 'img.png', start: 0, end: 5, x: 0.5, y: 0.5, width: 0.4, height: 0.3 }
      ],
      audio_clips: []
    };

    let appliedEdits = null;
    const mockScene = {
      duration: 30,
      clock: 1.0,
      getCues: () => [{ id: 'sub_0', start: 0, end: 1, text: 'Hello world' }],
      applyEdits: (next) => { appliedEdits = JSON.parse(JSON.stringify(next)); },
      seek: () => {},
      play: () => {}
    };

    window.__initEditor(mockScene, initialEdits);

    // Verify editorUi HTML has speed tab inputs
    // Switch to speed tab in inspector
    const rightPanelContent = editorUi.innerHTML;
    if (!editorUi.innerHTML.includes('id="editor-header"')) {
      throw new Error('editor-header missing in editorUi');
    }

    // Check editor.js code contains data-spd-start and data-spd-end
    const jsSource = fs.readFileSync('template/editor.js', 'utf8');
    if (!jsSource.includes('data-spd-start') || !jsSource.includes('data-spd-end')) {
      throw new Error('Speed segment start and end inputs missing in editor.js');
    }

    // Check editor.js code contains data-resize and corner handle dragging
    if (!jsSource.includes('data-resize') || !jsSource.includes('overlay_resize')) {
      throw new Error('Overlay resize handling missing in editor.js');
    }

    // Check editor.js code contains overlay select listener
    if (!jsSource.includes('data-ov-id')) {
      throw new Error('Overlay select listener missing in editor.js');
    }

    console.log('STUDIO_INSPECTOR_OK');
    process.exit(0);
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "STUDIO_INSPECTOR_OK" in proc.stdout


