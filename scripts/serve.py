#!/usr/bin/env python3
"""Static file server with HTTP Range support and Antigravity Studio REST API.

Provides:
- HTTP Range (206 Partial Content) support for video seeking.
- GET/POST /api/edits: reads and persists work/edits.json.
- GET/POST /api/assets: lists and uploads custom media/audio assets.
- GET /api/subtitles: returns dynamic 3-word subtitle cues from program.json + edits.json.
- POST /api/rebuild: runs cuts.py and build.py for rebuild workflow.

usage: python3 scripts/serve.py --project . [--port 5600]   ->  http://127.0.0.1:5600/scene/
"""
import argparse
import functools
import http.server
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from scripts.subtitles import chunk_three_words
except ImportError:
    try:
        from subtitles import chunk_three_words
    except ImportError:
        chunk_three_words = None

ALLOWED_EXTENSIONS = {'.mp3', '.wav', '.mp4', '.webm', '.png', '.jpg', '.jpeg', '.webp'}
ALLOWED_SOURCE_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv'}

MEDIA_TYPE_MAP = {
    '.png': 'image',
    '.jpg': 'image',
    '.jpeg': 'image',
    '.webp': 'image',
    '.mp4': 'video',
    '.webm': 'video',
    '.mp3': 'audio',
    '.wav': 'audio',
}

SFX_LIST = ["whoosh", "soft-whoosh", "tick", "click", "key", "typing", "pop", "chime"]


def default_edits() -> dict:
    """Return the default edits schema for work/edits.json."""
    return {
        "version": 1,
        "aspect": "9:16",
        "stage": {"width": 1080, "height": 1920},
        "subtitles": {
            "enabled": True,
            "x": 0.5,
            "y": 0.78,
            "fontSize": 56,
            "color": "#ffffff",
            "bgColor": "rgba(15, 17, 22, 0.78)",
            "uppercase": False,
            "overrides": {},
        },
        "speed_ranges": [],
        "deleted_ranges": [],
        "media_overlays": [],
        "audio_clips": [],
    }


def sanitize_source_filename(filename: str) -> str:
    """Sanitize and validate a source video filename.

    Strips directory traversal, replaces spaces and unsafe characters with '_',
    and verifies the extension is an allowed video source type. Raises ValueError on
    invalid, hidden, or disallowed files.
    """
    if not filename or not isinstance(filename, str):
        raise ValueError("Filename is empty or invalid")
    base = os.path.basename(filename.replace('\\', '/')).strip()
    if not base or base.startswith('.'):
        raise ValueError(f"Invalid or hidden filename: {filename}")
    name_part, ext = os.path.splitext(base)
    if not name_part or not ext or ext.lower() not in ALLOWED_SOURCE_EXTENSIONS:
        raise ValueError(f"Invalid filename or unsupported extension: {filename}")
    safe_name_part = re.sub(r'[^a-zA-Z0-9._-]', '_', name_part)
    if not safe_name_part:
        raise ValueError(f"Filename contains no valid characters: {filename}")
    return f"{safe_name_part}{ext}"


def sanitize_asset_filename(filename: str) -> str:
    """Sanitize and validate an asset filename.

    Strips directory traversal, replaces spaces and unsafe characters with '_',
    and verifies the extension is an allowed media type. Raises ValueError on
    invalid, hidden, or disallowed files.
    """
    if not filename or not isinstance(filename, str):
        raise ValueError("Filename is empty or invalid")
    base = os.path.basename(filename.replace('\\', '/')).strip()
    if not base or base.startswith('.'):
        raise ValueError(f"Invalid or hidden filename: {filename}")
    name_part, ext = os.path.splitext(base)
    if not name_part or not ext or ext.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid filename or unsupported extension: {filename}")
    safe_name_part = re.sub(r'[^a-zA-Z0-9._-]', '_', name_part)
    if not safe_name_part:
        raise ValueError(f"Filename contains no valid characters: {filename}")
    return f"{safe_name_part}{ext}"


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    project_root = None

    def __init__(self, *args, directory=None, **kwargs):
        if directory is None:
            if hasattr(self, 'project_root') and self.project_root:
                directory = self.project_root
            elif len(args) >= 3 and hasattr(args[2], 'project_root'):
                directory = args[2].project_root
            else:
                directory = os.getcwd()
        self._project_root = os.path.abspath(directory)
        super().__init__(*args, directory=self._project_root, **kwargs)

    @property
    def project_dir(self) -> str:
        return getattr(self, '_project_root', None) or getattr(self.server, 'project_root', os.getcwd())

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def _send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        clean_path = self.path.split('?')[0]
        if clean_path.endswith('/') and len(clean_path) > 1:
            clean_path = clean_path[:-1]

        if clean_path == '/api/edits':
            self._handle_get_edits()
        elif clean_path == '/api/assets':
            self._handle_get_assets()
        elif clean_path == '/api/subtitles':
            self._handle_get_subtitles()
        elif clean_path == '/api/project-status':
            self._handle_get_project_status()
        else:
            super().do_GET()

    def do_POST(self):
        clean_path = self.path.split('?')[0]
        if clean_path.endswith('/') and len(clean_path) > 1:
            clean_path = clean_path[:-1]

        if clean_path == '/api/edits':
            self._handle_post_edits()
        elif clean_path == '/api/assets':
            self._handle_post_assets()
        elif clean_path == '/api/rebuild':
            self._handle_post_rebuild()
        elif clean_path == '/api/source-video':
            self._handle_post_source_video()
        elif clean_path == '/api/init-project':
            self._handle_post_init_project()
        elif clean_path == '/api/export':
            self._handle_post_export()
        else:
            self._send_json({'ok': False, 'error': 'Endpoint not found'}, status=404)

    def _handle_get_edits(self):
        edits_path = os.path.join(self.project_dir, 'work', 'edits.json')
        if os.path.isfile(edits_path):
            try:
                with open(edits_path, encoding='utf-8') as f:
                    data = json.load(f)
                self._send_json(data)
                return
            except Exception:
                pass
        self._send_json(default_edits())

    def _handle_post_edits(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception as e:
            self._send_json({'ok': False, 'error': f'Invalid JSON: {e}'}, status=400)
            return

        if not isinstance(data, dict):
            self._send_json({'ok': False, 'error': 'Edits payload must be a JSON object'}, status=400)
            return

        work_dir = os.path.join(self.project_dir, 'work')
        os.makedirs(work_dir, exist_ok=True)
        edits_path = os.path.join(work_dir, 'edits.json')
        tmp_path = edits_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, edits_path)

        self._send_json({'ok': True, 'edits': data})

    def _handle_get_assets(self):
        assets_dir = os.path.join(self.project_dir, 'assets')
        assets = []
        if os.path.isdir(assets_dir):
            for entry in sorted(os.listdir(assets_dir)):
                if entry.startswith('.'):
                    continue
                full_path = os.path.join(assets_dir, entry)
                if not os.path.isfile(full_path):
                    continue
                ext = os.path.splitext(entry)[1].lower()
                mtype = MEDIA_TYPE_MAP.get(ext)
                if mtype:
                    assets.append({
                        'name': entry,
                        'url': f'../assets/{entry}',
                        'type': mtype,
                    })
        self._send_json({
            'assets': assets,
            'sfx': SFX_LIST,
        })

    def _handle_post_assets(self):
        filename = self.headers.get('X-Filename')
        if not filename:
            self._send_json({'ok': False, 'error': 'Missing X-Filename header'}, status=400)
            return

        try:
            safe_name = sanitize_asset_filename(filename)
        except ValueError as e:
            self._send_json({'ok': False, 'error': str(e)}, status=400)
            return

        ext = os.path.splitext(safe_name)[1].lower()
        media_type = MEDIA_TYPE_MAP.get(ext, 'unknown')

        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        assets_dir = os.path.join(self.project_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        dest_path = os.path.join(assets_dir, safe_name)
        with open(dest_path, 'wb') as f:
            f.write(body)

        self._send_json({
            'ok': True,
            'asset': {
                'name': safe_name,
                'url': f'../assets/{safe_name}',
                'type': media_type,
            }
        })

    def _handle_get_subtitles(self):
        prog_path = os.path.join(self.project_dir, 'work', 'program.json')
        words = []
        if os.path.isfile(prog_path):
            try:
                with open(prog_path, encoding='utf-8') as f:
                    pdata = json.load(f)
                    words = pdata.get('words', [])
            except Exception:
                words = []

        edits_path = os.path.join(self.project_dir, 'work', 'edits.json')
        overrides = {}
        uppercase = False
        if os.path.isfile(edits_path):
            try:
                with open(edits_path, encoding='utf-8') as f:
                    edata = json.load(f)
                    subs = edata.get('subtitles', {})
                    overrides = subs.get('overrides', {})
                    uppercase = bool(subs.get('uppercase', False))
            except Exception:
                pass

        if chunk_three_words is not None:
            cues = chunk_three_words(words, overrides=overrides, uppercase=uppercase)
        else:
            cues = []
        self._send_json({'cues': cues})

    def _handle_post_rebuild(self):
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        cuts_script = os.path.join(scripts_dir, 'cuts.py')
        build_script = os.path.join(scripts_dir, 'build.py')
        try:
            import subprocess
            if os.path.isfile(cuts_script):
                subprocess.run([sys.executable, cuts_script, '--project', self.project_dir], check=True)
            if os.path.isfile(build_script):
                subprocess.run([sys.executable, build_script, '--project', self.project_dir], check=True)
            self._send_json({'ok': True})
        except Exception as e:
            self._send_json({'ok': False, 'error': str(e)}, status=500)

    def _handle_get_project_status(self):
        prog_path = os.path.join(self.project_dir, 'work', 'program.json')
        proxy_path = os.path.join(self.project_dir, 'work', 'proxy.mp4')
        final_path = os.path.join(self.project_dir, 'out', 'FINAL.mp4')

        has_program = os.path.isfile(prog_path)
        has_proxy = os.path.isfile(proxy_path)
        has_final = os.path.isfile(final_path)

        src_dir = os.path.join(self.project_dir, 'src')
        src_files = []
        if os.path.isdir(src_dir):
            for entry in sorted(os.listdir(src_dir)):
                if entry.startswith('.'):
                    continue
                full_path = os.path.join(src_dir, entry)
                if not os.path.isfile(full_path):
                    continue
                ext = os.path.splitext(entry)[1].lower()
                if ext in ALLOWED_SOURCE_EXTENSIONS:
                    src_files.append(entry)

        self._send_json({
            'ok': True,
            'has_program': has_program,
            'has_proxy': has_proxy,
            'has_final': has_final,
            'src_files': src_files,
        })

    def _handle_post_source_video(self):
        filename = self.headers.get('X-Filename')
        if not filename:
            self._send_json({'ok': False, 'error': 'Missing X-Filename header'}, status=400)
            return

        try:
            safe_name = sanitize_source_filename(filename)
        except ValueError as e:
            self._send_json({'ok': False, 'error': str(e)}, status=400)
            return

        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        src_dir = os.path.join(self.project_dir, 'src')
        os.makedirs(src_dir, exist_ok=True)
        dest_path = os.path.join(src_dir, safe_name)
        with open(dest_path, 'wb') as f:
            f.write(body)

        self._send_json({
            'ok': True,
            'file': safe_name,
        })

    def _handle_post_init_project(self):
        src_dir = os.path.join(self.project_dir, 'src')
        candidates = []
        if os.path.isdir(src_dir):
            for entry in sorted(os.listdir(src_dir)):
                if entry.startswith('.'):
                    continue
                full_path = os.path.join(src_dir, entry)
                if not os.path.isfile(full_path):
                    continue
                ext = os.path.splitext(entry)[1].lower()
                if ext in ALLOWED_SOURCE_EXTENSIONS:
                    candidates.append(entry)

        if not candidates:
            self._send_json({'ok': False, 'error': 'No source video files found in src/'}, status=400)
            return

        stems = [os.path.splitext(f)[0] for f in candidates]
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        transcribe_script = os.path.join(scripts_dir, 'transcribe.py')
        auto_cut_script = os.path.join(scripts_dir, 'auto_cut.py')
        cuts_script = os.path.join(scripts_dir, 'cuts.py')
        build_script = os.path.join(scripts_dir, 'build.py')

        try:
            import subprocess
            if os.path.isfile(transcribe_script):
                for f in candidates:
                    subprocess.run(
                        [sys.executable, transcribe_script, '--project', self.project_dir, os.path.join('src', f)],
                        check=True,
                    )

            edl_path = os.path.join(self.project_dir, 'work', 'edl.json')
            if not os.path.isfile(edl_path):
                if os.path.isfile(auto_cut_script):
                    subprocess.run(
                        [sys.executable, auto_cut_script, '--project', self.project_dir, '--clip', stems[0]],
                        check=True,
                    )

            if os.path.isfile(cuts_script):
                subprocess.run([sys.executable, cuts_script, '--project', self.project_dir], check=True)

            if os.path.isfile(build_script):
                subprocess.run([sys.executable, build_script, '--project', self.project_dir], check=True)

            self._send_json({'ok': True, 'clips': stems})
        except Exception as e:
            self._send_json({'ok': False, 'error': str(e)}, status=500)

    def _handle_post_export(self):
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        render_script = os.path.join(scripts_dir, 'render.mjs')
        mix_script = os.path.join(scripts_dir, 'mix.py')
        port = getattr(self.server, 'server_port', 5600)

        try:
            import subprocess
            if os.path.isfile(render_script):
                subprocess.run(
                    ['node', render_script, '--project', self.project_dir, '--scene', f'http://127.0.0.1:{port}/scene/'],
                    check=True,
                )
            if os.path.isfile(mix_script):
                subprocess.run([sys.executable, mix_script, '--project', self.project_dir], check=True)

            self._send_json({'ok': True, 'download_url': '../out/FINAL.mp4'})
        except Exception as e:
            self._send_json({'ok': False, 'error': str(e)}, status=500)

    def send_head(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        m = re.match(r'bytes=(\d*)-(\d*)', rng)
        size = os.path.getsize(path)
        if not m:
            return super().send_head()
        start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2) or 0))
        end = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
        if start >= size or start > end:
            self.send_error(416)
            return None
        end = min(end, size - 1)
        f = open(path, 'rb')
        f.seek(start)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        left = getattr(self, '_remaining', None)
        if left is None:
            return super().copyfile(source, outputfile)
        try:
            while left > 0:
                buf = source.read(min(1 << 16, left))
                if not buf:
                    break
                outputfile.write(buf)
                left -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self._remaining = None

    def log_message(self, *args):
        pass


def create_server(project: str, port: int = 5600) -> http.server.ThreadingHTTPServer:
    """Create and return a configured ThreadingHTTPServer for the project."""
    project_root = os.path.abspath(project)
    handler = functools.partial(RangeHandler, directory=project_root)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    srv.project_root = project_root
    srv.server_port = srv.server_address[1]
    return srv


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', default='.')
    ap.add_argument('--port', type=int, default=5600)
    a = ap.parse_args()
    srv = create_server(a.project, a.port)
    print(f'serving {os.path.abspath(a.project)} on http://127.0.0.1:{a.port}/scene/')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
