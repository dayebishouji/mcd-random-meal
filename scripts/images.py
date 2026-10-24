"""Accept only unsigned HTTPS image links from the observed official menu CDNs."""
from urllib.parse import urlsplit


def official_image(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    try:
        url = urlsplit(value)
        if (url.scheme == 'https' and url.hostname in ('menu-img.mcd.cn', 'img.mcd.cn')
                and url.port in (None, 443) and not url.username and not url.password
                and not url.query and not url.fragment and url.path.startswith('/')):
            return value
    except ValueError:
        pass
    return None
