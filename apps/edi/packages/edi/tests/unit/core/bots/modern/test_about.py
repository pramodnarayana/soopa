from edi.core.bots import __about__
from edi.core.bots.__about__ import (
    __author__,
    __email__,
    __license__,
    __summary__,
    __title__,
    __url__,
)

"""
Tests for __about__.py metadata.
"""


def test_about_version():

    assert isinstance(__about__.__version__, str)
    assert len(__about__.__version__) > 0


def test_about_version_info():

    assert isinstance(__about__.__version_info__, list)
    assert len(__about__.__version_info__) >= 1


def test_about_title():

    assert __title__ == "bots-core"


def test_about_summary():

    assert "Bots" in __summary__


def test_about_license():

    assert "GPL" in __license__


def test_about_author():

    assert isinstance(__author__, str)


def test_about_email():

    assert "@" in __email__


def test_about_url():

    assert __url__.startswith("http")


def test_about_all_exports():

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
