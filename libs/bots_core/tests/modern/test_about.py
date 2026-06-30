"""
Tests for __about__.py metadata.
"""


def test_about_version():
    from bots_core import __about__

    assert isinstance(__about__.__version__, str)
    assert len(__about__.__version__) > 0


def test_about_version_info():
    from bots_core import __about__

    assert isinstance(__about__.__version_info__, list)
    assert len(__about__.__version_info__) >= 1


def test_about_title():
    from bots_core.__about__ import __title__

    assert __title__ == "bots-core"


def test_about_summary():
    from bots_core.__about__ import __summary__

    assert "Bots" in __summary__


def test_about_license():
    from bots_core.__about__ import __license__

    assert "GPL" in __license__


def test_about_author():
    from bots_core.__about__ import __author__

    assert isinstance(__author__, str)


def test_about_email():
    from bots_core.__about__ import __email__

    assert "@" in __email__


def test_about_url():
    from bots_core.__about__ import __url__

    assert __url__.startswith("http")


def test_about_all_exports():
    from bots_core import __about__

    expected = {
        "__version__",
        "__version_info__",
        "__title__",
        "__summary__",
        "__url__",
        "__author__",
        "__email__",
        "__license__",
    }
    assert expected.issubset(set(__about__.__all__))
