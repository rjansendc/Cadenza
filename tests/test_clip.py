import effects   # trigger registrations
from core.clip import Clip, ClipType
from core.track import Track, TrackType, Sequence
from core.commands import registry, register_command, CommandContext
from core.effects import StreamType

def test_clip_default_stack():
    clip = Clip(filepath='test.mp4')
    assert len(clip.effect_stack) > 0
    assert clip.get_effect('motion') is not None
    assert clip.get_effect('volume') is not None

def test_audio_only_clip():
    clip = Clip(filepath='music.wav',
                has_video=False, has_audio=True)
    assert clip.get_effect('motion') is None
    assert clip.get_effect('volume') is not None

def test_visible_effects_video_clip():
    clip = Clip(filepath='test.mp4',
                has_video=True, has_audio=True)
    visible = clip.visible_effects()
    types = [e.stream_type for e in visible]
    assert StreamType.VIDEO in types
    assert StreamType.AUDIO in types

def test_scale_to_frame():
    clip = Clip(filepath='test.mp4',
                source_width=3840, source_height=2160)
    clip.scale_to_frame(1920, 1080)
    motion = clip.get_effect('motion')
    assert motion.get('scale') == 50.0

def test_track_z_order():
    seq = Sequence()
    assert seq.video_tracks[0].z_order == 1000
    assert seq.video_tracks[1].z_order == 1001
    assert seq.audio_tracks[0].z_order == 0
    assert seq.audio_tracks[1].z_order == 1

def test_tracks_render_order():
    seq = Sequence()
    ordered = seq.all_tracks_by_z()
    z_values = [t.z_order for t in ordered]
    assert z_values == sorted(z_values)

def test_command_registry():
    def dummy(**kwargs): return 'ok'
    register_command('test_cmd', 'Test',
                     dummy, CommandContext.CLIP)
    assert registry.execute('test_cmd') == 'ok'