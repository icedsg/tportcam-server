import pytest

from tests.onvif_sim import Camera


@pytest.fixture
def cam():
    c = Camera().start()
    yield c
    c.stop()


@pytest.fixture
def digest_cam():
    c = Camera(auth="http-digest", name="Digest%20Cam").start()
    yield c
    c.stop()
