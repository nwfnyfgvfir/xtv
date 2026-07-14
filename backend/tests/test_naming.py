from app.services.naming import extract_number, normalize_number


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


def test_normalize_number_empty():
    assert normalize_number(None) is None
    assert normalize_number("") is None
    assert normalize_number("   ") is None


def test_normalize_number_standard():
    assert normalize_number("ssis-001") == "SSIS-001"
    assert normalize_number("SSIS_001") == "SSIS-001"
    assert normalize_number(" ssis 001 ") == "SSIS-001"


def test_normalize_number_fc2():
    assert normalize_number("FC2-PPV-1234567") == "FC2-1234567"


def test_normalize_number_fallback_and_truncate():
    assert normalize_number("weird--code") == "WEIRD-CODE"
    long = "A" * 80
    assert normalize_number(long) == "A" * 64
