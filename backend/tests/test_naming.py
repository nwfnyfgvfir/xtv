from app.services.naming import extract_number


def test_standard():
    p = extract_number("SSIS-001.mp4")
    assert p.number == "SSIS-001"


def test_standard_lower():
    p = extract_number("ssis-001.mkv")
    assert p.number == "SSIS-001"


def test_with_c_subtitle():
    p = extract_number("ABC-330-C.mp4")
    assert p.number == "ABC-330"
    assert p.subtitle_flag == "C"


def test_multi_disc():
    p = extract_number("ABC-330-cd1.mp4")
    assert p.number == "ABC-330"
    assert p.disc == "cd1"


def test_fc2():
    p = extract_number("FC2-PPV-1234567.mp4")
    assert p.number == "FC2-1234567"


def test_heyzo():
    p = extract_number("HEYZO-1234.mp4")
    assert p.number == "HEYZO-1234"


def test_quality_noise():
    p = extract_number("SSIS-001-1080p-x264.mp4")
    assert p.number == "SSIS-001"


def test_no_match():
    p = extract_number("random_video.mp4")
    assert p.number is None
