"""
Configuration, plugins and fixtures for `pytest`.
"""

import base64
import io
import os
import random
from typing import Generator

import pytest
from _pytest.fixtures import SubRequest
from PIL import Image
from requests_mock import GET

from mock_vws import MockVWS, States
from tests.mock_vws.utils import (
    TargetAPIEndpoint,
    VuforiaDatabaseKeys,
    add_target_to_vws,
    delete_target,
    target_api_request,
)

# from tests.mock_vws.prepared_request_fixtures import *
pytest_plugins = ['tests.mock_vws.prepared_request_fixtures']


def _image_file(
    file_format: str,
    color_space: str,
    width: int,
    height: int,
) -> io.BytesIO:
    """
    Return an image file in the given format and color space.

    The image file is filled with randomly colored pixels.

    Args:
        file_format: See
            http://pillow.readthedocs.io/en/3.1.x/handbook/image-file-formats.html
        color_space: One of "L", "RGB", or "CMYK". "L" means greyscale.
        width: The width, in pixels of the image.
        height: The width, in pixels of the image.

    Returns:
        An image file in the given format and color space.
    """
    image_buffer = io.BytesIO()
    image = Image.new(color_space, (width, height))
    pixels = image.load()
    for i in range(height):
        for j in range(width):
            red = random.randint(0, 255)
            green = random.randint(0, 255)
            blue = random.randint(0, 255)
            if color_space != 'L':
                pixels[i, j] = (red, green, blue)
    image.save(image_buffer, file_format)
    image_buffer.seek(0)
    return image_buffer


@pytest.fixture
def png_rgb_success() -> io.BytesIO:
    """
    Return a PNG file in the RGB color space which is expected to have a
    'success' status when added to a target.
    """
    return _image_file(file_format='PNG', color_space='RGB', width=5, height=5)


@pytest.fixture
def png_rgb() -> io.BytesIO:
    """
    Return a 1x1 PNG file in the RGB color space.
    """
    return _image_file(file_format='PNG', color_space='RGB', width=1, height=1)


@pytest.fixture
def png_greyscale() -> io.BytesIO:
    """
    Return a 1x1 PNG file in the greyscale color space.
    """
    return _image_file(file_format='PNG', color_space='L', width=1, height=1)


@pytest.fixture()
def png_large(
    png_rgb: io.BytesIO,  # pylint: disable=redefined-outer-name
) -> io.BytesIO:
    """
    Return a PNG file of the maximum allowed file size.

    https://library.vuforia.com/articles/Training/Cloud-Recognition-Guide
    describes that the maximum allowed file size of an image is 2 MB.
    However, tests using this fixture demonstrate that the maximum allowed
    size is actually slightly greater than that.
    """
    png_size = len(png_rgb.getbuffer())
    max_size = 2359293
    filler_length = max_size - png_size
    filler_data = b'\x00' * int(filler_length)
    original_data = png_rgb.getvalue()
    longer_data = original_data.replace(b'IEND', filler_data + b'IEND')
    png = io.BytesIO(longer_data)
    return png


@pytest.fixture
def jpeg_cmyk() -> io.BytesIO:
    """
    Return a 1x1 JPEG file in the CMYK color space.
    """
    return _image_file(
        file_format='JPEG',
        color_space='CMYK',
        width=1,
        height=1,
    )


@pytest.fixture
def jpeg_rgb() -> io.BytesIO:
    """
    Return a 1x1 JPEG file in the RGB color space.
    """
    return _image_file(
        file_format='JPEG',
        color_space='RGB',
        width=1,
        height=1,
    )


@pytest.fixture
def tiff_rgb() -> io.BytesIO:
    """
    Return a 1x1 TIFF file in the RGB color space.

    This is given as an option which is not supported by Vuforia as Vuforia
    supports only JPEG and PNG files.
    """
    return _image_file(
        file_format='TIFF',
        color_space='RGB',
        width=1,
        height=1,
    )


@pytest.fixture(params=['png_rgb', 'jpeg_rgb', 'png_greyscale', 'png_large'])
def image_file(request: SubRequest) -> io.BytesIO:
    """
    Return an image file which is expected to work on Vuforia.

    "work" means that this will be added as a target. However, this may or may
    not result in target with a 'success' status.
    """
    file_bytes_io: io.BytesIO = request.getfixturevalue(request.param)
    return file_bytes_io


@pytest.fixture(params=['tiff_rgb', 'jpeg_cmyk'])
def bad_image_file(request: SubRequest) -> io.BytesIO:
    """
    Return an image file which is expected to work on Vuforia which is
    expected to cause a `BadImage` result when an attempt is made to add it to
    the target database.
    """
    file_bytes_io: io.BytesIO = request.getfixturevalue(request.param)
    return file_bytes_io


@pytest.fixture()
def high_quality_image() -> io.BytesIO:
    """
    Return an image file which is expected to have a 'success' status when
    added to a target and a high tracking rating.

    At the time of writing, this image gains a tracking rating of 5.
    """
    path = 'tests/mock_vws/data/high_quality_image.jpg'
    with open(path, 'rb') as high_quality_image_file:
        return io.BytesIO(high_quality_image_file.read())


def _delete_all_targets(database_keys: VuforiaDatabaseKeys) -> None:
    """
    Delete all targets.

    Args:
        database_keys: The credentials to the Vuforia target database to delete
            all targets in.
    """
    response = target_api_request(
        server_access_key=database_keys.server_access_key,
        server_secret_key=database_keys.server_secret_key,
        method=GET,
        content=b'',
        request_path='/targets',
    )

    if 'results' not in response.json():  # pragma: no cover
        print('Results not found.')
        print('Response is:')
        print(response.json())

    targets = response.json()['results']

    for target in targets:
        delete_target(vuforia_database_keys=database_keys, target_id=target)


@pytest.fixture()
def target_id(
    png_rgb_success: io.BytesIO,  # pylint: disable=redefined-outer-name
    vuforia_database_keys: VuforiaDatabaseKeys,  # noqa: E501 pylint: disable=redefined-outer-name
) -> str:
    """
    Return the target ID of a target in the database.

    The target is one which will have a 'success' status when processed.
    """
    image_data = png_rgb_success.read()
    image_data_encoded = base64.b64encode(image_data).decode('ascii')

    data = {
        'name': 'example',
        'width': 1,
        'image': image_data_encoded,
    }

    response = add_target_to_vws(
        vuforia_database_keys=vuforia_database_keys,
        data=data,
        content_type='application/json',
    )

    return str(response.json()['target_id'])


@pytest.fixture(params=[True, False], ids=['Real Vuforia', 'Mock Vuforia'])
def verify_mock_vuforia(
    request: SubRequest,
    vuforia_database_keys: VuforiaDatabaseKeys,  # noqa: E501 pylint: disable=redefined-outer-name
) -> Generator:
    """
    Test functions which use this fixture are run twice. Once with the real
    Vuforia, and once with the mock.

    This is useful for verifying the mock.
    """
    skip_real = os.getenv('SKIP_REAL') == '1'
    skip_mock = os.getenv('SKIP_MOCK') == '1'

    use_real_vuforia = request.param

    if use_real_vuforia and skip_real:  # pragma: no cover
        pytest.skip()

    if not use_real_vuforia and skip_mock:  # pragma: no cover
        pytest.skip()

    if use_real_vuforia:
        _delete_all_targets(database_keys=vuforia_database_keys)
        yield
    else:
        with MockVWS(
            database_name=vuforia_database_keys.database_name,
            server_access_key=vuforia_database_keys.server_access_key.
            decode('ascii'),
            server_secret_key=vuforia_database_keys.server_secret_key.
            decode('ascii'),
            processing_time_seconds=0.1,
        ):
            yield


@pytest.fixture(params=[True, False], ids=['Real Vuforia', 'Mock Vuforia'])
def verify_mock_vuforia_inactive(
    request: SubRequest,
    inactive_database_keys: VuforiaDatabaseKeys,  # noqa: E501 pylint: disable=redefined-outer-name
) -> Generator:
    """
    Test functions which use this fixture are run twice. Once with the real
    Vuforia in an inactive state, and once with the mock in an inactive state.

    This is useful for verifying the mock.

    To create an inactive project, delete the license key associated with a
    database.
    """
    skip_real = os.getenv('SKIP_REAL') == '1'
    skip_mock = os.getenv('SKIP_MOCK') == '1'

    use_real_vuforia = request.param

    if use_real_vuforia and skip_real:  # pragma: no cover
        pytest.skip()

    if not use_real_vuforia and skip_mock:  # pragma: no cover
        pytest.skip()

    if use_real_vuforia:
        yield
    else:
        with MockVWS(
            state=States.PROJECT_INACTIVE,
            database_name=inactive_database_keys.database_name,
            server_access_key=inactive_database_keys.server_access_key.
            decode('ascii'),
            server_secret_key=inactive_database_keys.server_secret_key.
            decode('ascii'),
        ):
            yield


@pytest.fixture(
    params=[
        '_add_target',
        '_database_summary',
        '_delete_target',
        '_get_duplicates',
        '_get_target',
        '_target_list',
        '_target_summary',
        '_update_target',
    ]
)
def endpoint(request: SubRequest) -> TargetAPIEndpoint:
    """
    Return details of an endpoint.
    """
    endpoint_fixture: TargetAPIEndpoint = request.getfixturevalue(
        request.param
    )
    return endpoint_fixture


@pytest.fixture()
def vuforia_database_keys() -> VuforiaDatabaseKeys:
    """
    Return VWS credentials from environment variables.
    """
    credentials: VuforiaDatabaseKeys = VuforiaDatabaseKeys(
        database_name=os.environ['VUFORIA_TARGET_MANAGER_DATABASE_NAME'],
        server_access_key=os.environ['VUFORIA_SERVER_ACCESS_KEY'],
        server_secret_key=os.environ['VUFORIA_SERVER_SECRET_KEY'],
        client_access_key=os.environ['VUFORIA_CLIENT_ACCESS_KEY'],
        client_secret_key=os.environ['VUFORIA_CLIENT_SECRET_KEY'],
    )
    return credentials


@pytest.fixture()
def inactive_database_keys() -> VuforiaDatabaseKeys:
    """
    Return VWS credentials for an inactive project from environment variables.
    """
    credentials: VuforiaDatabaseKeys = VuforiaDatabaseKeys(
        database_name=os.
        environ['INACTIVE_VUFORIA_TARGET_MANAGER_DATABASE_NAME'],
        server_access_key=os.environ['INACTIVE_VUFORIA_SERVER_ACCESS_KEY'],
        server_secret_key=os.environ['INACTIVE_VUFORIA_SERVER_SECRET_KEY'],
        client_access_key=os.environ['INACTIVE_VUFORIA_SERVER_ACCESS_KEY'],
        client_secret_key=os.environ['INACTIVE_VUFORIA_SERVER_SECRET_KEY'],
    )
    return credentials
