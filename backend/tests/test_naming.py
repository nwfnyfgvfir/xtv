import pytest

from app.services.naming import source_name


@pytest.mark.parametrize('filename, expected', [
    ('FC2-PPV-1066192.mp4', 'FC2-PPV-1066192'),
    ('fc2_ppv_1066192.mkv', 'fc2_ppv_1066192'),
    ('FC2-1066192.ts', 'FC2-1066192'),
    ('ＳＳＩＳ－００１.mp4', 'ＳＳＩＳ－００１'),
    ('SSIS–001.mp4', 'SSIS–001'),
    ('SSIS.001.mp4', 'SSIS.001'),
    ('site.example@SSIS-001-1080p-x264.mp4', 'site.example@SSIS-001-1080p-x264'),
    ('ABC-330-C.mp4', 'ABC-330-C'),
    ('ABC-330-cd1.mp4', 'ABC-330-cd1'),
    ('中文标题SSIS001中字.strm', '中文标题SSIS001中字'),
    ('SSIS-001 SSIS-002.mp4', 'SSIS-001 SSIS-002'),
    ('random_video.mp4', 'random_video'),
    ('010124_001.mp4', '010124_001'),
    ('A' * 200 + '.mp4', 'A' * 200),
])
def test_source_filename_is_passed_through_without_catalog_recognition(filename, expected):
    assert source_name(filename) == expected
