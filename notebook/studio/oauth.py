"""Instagram Business Login helpers.

The app secret is consumed only by this local module. It is never sent to the
browser or copied to the web server.
"""
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json


SCOPES = ("instagram_business_basic", "instagram_business_content_publish")


def authorize_url(app_id: str, redirect_uri: str, state: str, force_reauth: bool = False) -> str:
    query = urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
        "force_reauth": "true" if force_reauth else "false",
        "enable_fb_login": "false",
    })
    return "https://www.instagram.com/oauth/authorize?" + query


def strip_code(raw: str) -> str:
    return raw[:-2] if raw.endswith("#_") else raw


def exchange_code(app_id: str, app_secret: str, redirect_uri: str, code: str, http) -> dict:
    short = http(
        "https://api.instagram.com/oauth/access_token",
        method="POST",
        form={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": strip_code(code),
        },
    )
    record = short.get("data", [short])[0]
    short_token = record.get("access_token")
    user_id = str(record.get("user_id") or "")
    if not isinstance(short_token, str) or len(short_token) < 20 or not user_id.isdigit():
        raise RuntimeError("Meta did not return a valid short-lived token")

    long_lived = http(
        "https://graph.instagram.com/access_token",
        method="GET",
        query={
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret,
            "access_token": short_token,
        },
    )
    token = long_lived.get("access_token")
    expires_in = long_lived.get("expires_in")
    if not isinstance(token, str) or len(token) < 20 or not isinstance(expires_in, int):
        raise RuntimeError("Meta did not return a valid long-lived token")
    return {"access_token": token, "user_id": user_id, "expires_in": expires_in}


CONNECTION_ERROR = ("Instagram konnte die Verbindung nicht bestätigen. Prüfe dein Creator- oder Business-Konto "
                    "und beide Freigaben. Solange Meta die Rechte nur zum Testen freigibt, brauchst du "
                    "zusätzlich eine angenommene Tester-Einladung.")


def meta_http(url: str, *, method: str = "GET", form=None, query=None, token=None) -> dict:
    if query:
        url += "?" + urlencode(query)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=urlencode(form).encode() if form is not None else None,
                      method=method, headers=headers)
    try:
        with urlopen(request, timeout=25) as response:
            result = json.loads(response.read(1_000_000))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (HTTPError, URLError, OSError, ValueError):
        raise RuntimeError(CONNECTION_ERROR) from None


def identity(token: str, http=meta_http) -> dict:
    result = http("https://graph.instagram.com/v26.0/me",
                  query={"fields": "user_id,username,account_type"}, token=token)
    user_id = str(result.get("user_id", ""))
    if not user_id.isdigit() or not isinstance(result.get("username"), str):
        raise RuntimeError(CONNECTION_ERROR)
    if result.get("account_type") not in {"BUSINESS", "MEDIA_CREATOR"}:
        raise RuntimeError("Bitte verwende ein professionelles Instagram-Konto (Creator oder Business).")
    return {"id": user_id, "username": result["username"]}
