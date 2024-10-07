import pytest

from cat.looking_glass.cheshire_cat import CheshireCat
from cat.mad_hatter.mad_hatter import MadHatter
from cat.rabbit_hole import RabbitHole


def get_class_from_decorated_singleton(singleton):
    return singleton().__class__


@pytest.fixture
def cheshire_cat(client):
    yield CheshireCat()  # don't panic, it's a singleton


def test_main_modules_loaded(cheshire_cat):
    assert isinstance(
        cheshire_cat.mad_hatter, get_class_from_decorated_singleton(MadHatter)
    )

    assert isinstance(
        cheshire_cat.rabbit_hole, get_class_from_decorated_singleton(RabbitHole)
    )
