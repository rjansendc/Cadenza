import effects
from core.project import Project, MediaPoolItem
from core.track import SequenceSettings

def test_project_creation():
    p = Project(name='Test Project')
    assert p.name == 'Test Project'
    assert p.active_sequence is not None
    assert len(p.sequences) == 1

def test_import_media():
    p = Project()
    item = p.import_media('test.mp4')
    assert item.name == 'test.mp4'
    assert item.id in p.media_pool
    assert p.is_dirty == True

def test_add_clip_to_timeline():
    p = Project()
    item = p.import_media('test.mp4')
    item.source_width  = 3840
    item.source_height = 2160
    item.source_frames = 1000
    clip = p.add_clip(item, track=0, start_frame=0)
    assert clip.id in p.clips
    assert clip.track == 0
    # should have been auto-scaled to 1080p canvas
    motion = clip.get_effect('motion')
    assert motion.get('scale') == 50.0

def test_get_clips_at_frame():
    p = Project()
    item = p.import_media('test.mp4')
    item.source_frames = 100
    item.out_point = 100
    p.add_clip(item, track=0, start_frame=0)
    p.add_clip(item, track=1, start_frame=50)
    at_frame_60 = p.get_clips_at_frame(60)
    assert len(at_frame_60) == 2
    at_frame_10 = p.get_clips_at_frame(10)
    assert len(at_frame_10) == 1

def test_multiple_sequences():
    p = Project()
    seq2 = p.add_sequence('Concert B Roll')
    assert len(p.sequences) == 2
    assert seq2.name == 'Concert B Roll'

def test_media_pool_repr():
    item = MediaPoolItem(
        filepath='MVI_0104.mp4',
        source_width=1920,
        source_height=1080,
        source_fps=29.97,
        source_duration=36.5
    )
    assert '1080p' in repr(item)