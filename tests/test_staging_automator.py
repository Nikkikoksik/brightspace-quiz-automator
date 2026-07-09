import staging_automator as sa


def test_extract_ou_from_course_home_url():
    assert sa._extract_ou("https://learn.okanagancollege.ca/d2l/home/13188") == "13188"


def test_extract_ou_from_tool_query_url():
    assert (
        sa._extract_ou(
            "https://learn.okanagancollege.ca/d2l/lms/grades/index.d2l?ou=13188"
        )
        == "13188"
    )


def test_extract_ou_from_lessons_url():
    assert (
        sa._extract_ou("https://learn.okanagancollege.ca/d2l/le/lessons/13188")
        == "13188"
    )
