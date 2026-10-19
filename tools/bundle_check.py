"""Exercise the installed bundle without a development Python environment."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback


def run():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    report = {'frozen': bool(getattr(sys, 'frozen', False)), 'checks': {}}
    window = None
    try:
        import av
        import torch
        import sounddevice as sd
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QImage, QColor
        from PySide6.QtWidgets import QApplication
        from core.version import __version__
        from core.proxy import ffmpeg_path
        from core.project_io import save_project, load_project
        from render.export_config import ExportConfig
        from render.exporter import ExportThread
        from ui.mainwindow import MainWindow
        from ui import recent_files

        report.update(version=__version__, python=sys.version.split()[0],
                      torch=torch.__version__, cuda=torch.cuda.is_available())
        checks = report['checks']
        with tempfile.TemporaryDirectory(prefix='cadenza-check-') as directory:
            root = Path(directory)
            recent_files.settings = lambda: QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
            app = QApplication.instance() or QApplication([])
            window = MainWindow()
            window.show()
            app.processEvents()
            checks['window'] = window.isVisible()
            checks['icon'] = not window.windowIcon().isNull()
            media_paths = []
            for index in range(6):
                image = QImage(320, 180, QImage.Format.Format_RGB32)
                image.fill(QColor.fromHsv(index * 60, 180, 210))
                path = root / f'still-{index}.png'
                if not image.save(str(path)):
                    raise RuntimeError('PNG plugin unavailable')
                media_paths.append(str(path))
            window._on_import_paths(media_paths)
            app.processEvents()
            state = window.app_state
            scale = state.px_per_frame
            start = 0
            row = len(window.project.active_sequence.video_tracks) - 1
            for item in window.project.media_pool.values():
                window._on_media_dropped(item.id, row, start)
                start += item.source_frames
                if state.px_per_frame != scale:
                    raise RuntimeError('Dropping a still changed zoom')
            checks['six_stills'] = len(window.project.clips) == 6
            path = root / 'show.veproj'
            if not save_project(window.project, str(path)):
                raise RuntimeError('Project save failed')
            checks['project_roundtrip'] = len(load_project(str(path)).clips) == 6

            compositor = window._playback._compositor
            compositor.set_preview_size(320, 180)
            clips = list(window.project.clips.values())
            for clip in clips:
                tensor = compositor.composite_frame(clips, clip.start_frame + 1)
                if tuple(tensor.shape) != (180, 320, 3) or tensor.max().item() == 0:
                    raise RuntimeError(f'Blank preview: {clip.name}')
            checks['preview'] = True
            checks['audio_devices'] = len(sd.query_devices())
            if sd.query_devices():
                with sd.OutputStream(samplerate=48000, channels=2, dtype='float32') as stream:
                    checks['audio_stream'] = stream.active

            ffmpeg = ffmpeg_path()
            if not ffmpeg:
                raise RuntimeError('Bundled FFmpeg not found')
            checks['ffmpeg'] = subprocess.run(
                [ffmpeg, '-version'], check=True, capture_output=True, text=True
            ).stdout.splitlines()[0]
            subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'lavfi', '-i', 'color=size=320x180:rate=30',
                '-frames:v', '3', '-c:v', 'libx264', str(root / 'proxy.mp4'),
            ], check=True, capture_output=True)
            checks['ffmpeg_encode'] = True

            encoders = ['h264']
            if torch.cuda.is_available():
                encoders.append('h264_nvenc')
            for encoder in encoders:
                output = root / f'{encoder}.mp4'
                config = ExportConfig(output_path=str(output), width=320, height=180,
                                      end_frame=3, encoder=encoder)
                job = ExportThread(config, clips, window.project.active_sequence, compositor)
                errors = []
                job.error.connect(errors.append)
                job.run()
                if errors:
                    raise RuntimeError('; '.join(errors))
                with av.open(str(output)) as container:
                    decoded = list(container.decode(video=0))
                if len(decoded) != 3 or decoded[0].to_ndarray().max() == 0:
                    raise RuntimeError(f'Invalid {encoder} export')
                checks[f'export_{encoder}'] = True
            window.mark_saved()
            window._on_close_project()
            checks['close_project'] = (
                not window.project.clips and not window.project.media_pool
                and not window.project.is_dirty
            )
            if not checks['close_project']:
                raise RuntimeError('Close Project did not reset the project')
            window.close()
            window._playback._mixer.stop()
            window._playback._mixer.join(timeout=2)
            window = None
            app.processEvents()
        report['ok'] = True
    except Exception:
        report.update(ok=False, error=traceback.format_exc())
    finally:
        if window is not None:
            # Only generated test data is discarded during failure cleanup.
            window.project.is_dirty = False
            window.close()
            if getattr(window, '_playback', None):
                window._playback.pause()
                window._playback._mixer.stop()
                window._playback._mixer.join(timeout=2)
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report.get('ok') else 1
