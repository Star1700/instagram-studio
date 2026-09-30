import pytest
from studio.server_api import parse_upload_response


def test_upload_response_has_public_random_jpeg():
    post_id = 'a' * 32
    parsed = parse_upload_response({'id': post_id, 'status': 'scheduled',
                                   'image_url': f'https://www.starseven.at/ig-out/{post_id}.jpg'})
    assert parsed.id == post_id
    assert parsed.status == 'scheduled'
    assert parsed.image_url.endswith(f'/{post_id}.jpg')


@pytest.mark.parametrize('body', [{}, {'id': '../../wp-config', 'status': 'sent', 'image_url': 'http://bad/'}])
def test_bad_upload_response_is_rejected(body):
    with pytest.raises(ValueError):
        parse_upload_response(body)
