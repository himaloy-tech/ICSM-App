"""Small local API server for Quadfit's private AI and Strava integrations."""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SESSIONS: dict[str, dict] = {}
MAX_BODY = 10 * 1024 * 1024


def load_local_env():
    """Load optional local credentials without requiring a dotenv package."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value:
            os.environ.setdefault(key, value)


load_local_env()
PORT = int(os.environ.get("PORT", "8000"))


class QuadfitHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Avoid logging callback query strings, which contain short-lived OAuth codes.
        path = urllib.parse.urlparse(self.path).path
        print(f"{self.client_address[0]} - - [{self.log_date_time_string()}] {self.command} {path}")

    def _json(self, data, status=200, headers=None):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("Request is empty or larger than 10 MB.")
        return json.loads(self.rfile.read(length))

    def _session_id(self, create=False):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "quadfit_session" and value in SESSIONS:
                return value
        if create:
            session_id = secrets.token_urlsafe(24)
            SESSIONS[session_id] = {}
            return session_id
        return None

    def _set_session_cookie(self, session_id):
        return {"Set-Cookie": f"quadfit_session={session_id}; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400"}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            session = SESSIONS.get(self._session_id() or "", {})
            self._json({
                "aiConfigured": bool(os.environ.get("OPENAI_API_KEY")),
                "stravaConfigured": bool(os.environ.get("STRAVA_CLIENT_ID") and os.environ.get("STRAVA_CLIENT_SECRET") and os.environ.get("STRAVA_REDIRECT_URI")),
                "stravaConnected": bool(session.get("strava")),
            })
            return
        if parsed.path == "/api/strava/connect":
            client_id = os.environ.get("STRAVA_CLIENT_ID")
            redirect_uri = os.environ.get("STRAVA_REDIRECT_URI")
            if not client_id or not os.environ.get("STRAVA_CLIENT_SECRET") or not redirect_uri:
                self._json({"error": "Strava is not configured on this server yet."}, 503)
                return
            session_id = self._session_id(create=True)
            state = secrets.token_urlsafe(24)
            SESSIONS[session_id]["strava_oauth_state"] = state
            query = urllib.parse.urlencode({
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "approval_prompt": "auto",
                "scope": "read,activity:read_all",
                "state": state,
            })
            self.send_response(302)
            self.send_header("Location", "https://www.strava.com/oauth/authorize?" + query)
            self.send_header("Cache-Control", "no-store")
            for key, value in self._set_session_cookie(session_id).items():
                self.send_header(key, value)
            self.end_headers()
            return
        if parsed.path == "/api/strava/callback":
            query = urllib.parse.parse_qs(parsed.query)
            session_id = self._session_id()
            session = SESSIONS.get(session_id or "", {})
            code = query.get("code", [""])[0]
            state = query.get("state", [""])[0]
            if not code or not state or not secrets.compare_digest(state, session.get("strava_oauth_state", "")):
                self._json({"error": "Strava authorization could not be verified. Please reconnect."}, 400)
                return
            try:
                tokens = self._strava_token({"grant_type": "authorization_code", "code": code})
                session["strava"] = tokens
                session.pop("strava_oauth_state", None)
                self.send_response(302)
                self.send_header("Location", "/?connected=strava#account")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            except Exception:
                self._json({"error": "Strava could not complete the connection. Check the server credentials and callback URL."}, 502)
            return
        if parsed.path == "/api/strava/activities":
            session = SESSIONS.get(self._session_id() or "", {})
            if not session.get("strava"):
                self._json({"error": "Connect Strava first."}, 401)
                return
            try:
                token = self._valid_strava_access_token(session)
                start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                params = urllib.parse.urlencode({"after": int(start.timestamp()), "per_page": 100})
                request = urllib.request.Request(
                    "https://www.strava.com/api/v3/athlete/activities?" + params,
                    headers={"Authorization": "Bearer " + token, "User-Agent": "Quadfit fitness dashboard"},
                )
                with urllib.request.urlopen(request, timeout=20) as response:
                    raw = json.loads(response.read())
                activities = [{
                    "id": str(item.get("id", "")),
                    "name": item.get("name") or item.get("type") or "Workout",
                    "date": (item.get("start_date_local") or item.get("start_date") or "")[:10],
                    "calories": int(round(item.get("calories") or 0)),
                    "duration": int(round((item.get("elapsed_time") or 0) / 60)),
                    "type": item.get("type") or "Workout",
                } for item in raw if item.get("id")]
                self._json({"activities": activities})
            except Exception:
                self._json({"error": "Could not load activities from Strava. Try reconnecting."}, 502)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/analyze-meal":
                self._analyze_meal()
                return
            if parsed.path == "/api/strava/disconnect":
                session = SESSIONS.get(self._session_id() or "", {})
                tokens = session.pop("strava", None)
                if tokens:
                    request = urllib.request.Request(
                        "https://www.strava.com/oauth/deauthorize",
                        data=urllib.parse.urlencode({"access_token": tokens.get("access_token", "")}).encode(),
                        method="POST",
                    )
                    try:
                        urllib.request.urlopen(request, timeout=10).read()
                    except Exception:
                        pass
                self._json({"ok": True})
                return
            self._json({"error": "Not found."}, 404)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception:
            self._json({"error": "The request could not be completed."}, 502)

    def _analyze_meal(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self._json({"error": "AI photo analysis is not configured on this server. Add an OpenAI API key to enable it."}, 503)
            return
        payload = self._body()
        image = payload.get("image", "") if isinstance(payload, dict) else ""
        if not isinstance(image, str) or len(image) > 9_000_000 or not image.startswith("data:image/jpeg;base64,"):
            raise ValueError("Choose a valid food photo under 7 MB after compression.")
        try:
            base64.b64decode(image.partition(",")[2], validate=True)
        except Exception as exc:
            raise ValueError("The photo data could not be read.") from exc
        request_body = {
            "model": os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": "Identify visible foods in this meal photo and estimate calories for the visible portion. Return JSON with keys meal (short meal description), foods (array of food names), calories (integer estimate), and note (brief uncertainty note). Do not claim exact precision. If the image is not food, return meal='Unable to identify a meal', foods=[], calories=0, and explain in note."},
                {"type": "input_image", "image_url": image, "detail": "low"},
            ]}],
            "text": {"format": {"type": "json_object"}},
            "max_output_tokens": 240,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(request_body).encode(),
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            print("OpenAI meal analysis returned HTTP", exc.code)
            self._json({"error": "The AI service could not analyze this image. Check the API key and account limits."}, 502)
            return
        output_text = "".join(
            block.get("text", "")
            for item in result.get("output", [])
            for block in item.get("content", [])
            if block.get("type") == "output_text"
        )
        try:
            estimate = json.loads(output_text)
            calories = int(estimate.get("calories", 0))
            if not estimate.get("meal") or calories < 0 or calories > 10000:
                raise ValueError
        except Exception:
            self._json({"error": "The AI returned an incomplete meal estimate. Try another photo."}, 502)
            return
        self._json({
            "meal": str(estimate["meal"])[:100],
            "foods": [str(food)[:60] for food in estimate.get("foods", [])[:12]],
            "calories": calories,
            "note": str(estimate.get("note", "Calories are approximate."))[:250],
        })

    def _strava_token(self, fields):
        data = {
            "client_id": os.environ.get("STRAVA_CLIENT_ID", ""),
            "client_secret": os.environ.get("STRAVA_CLIENT_SECRET", ""),
            **fields,
        }
        request = urllib.request.Request(
            "https://www.strava.com/oauth/token",
            data=urllib.parse.urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())

    def _valid_strava_access_token(self, session):
        tokens = session["strava"]
        if int(tokens.get("expires_at", 0)) < time.time() + 60:
            tokens = self._strava_token({"grant_type": "refresh_token", "refresh_token": tokens.get("refresh_token", "")})
            session["strava"] = tokens
        return tokens["access_token"]


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), QuadfitHandler)
    print(f"Quadfit is available at http://127.0.0.1:{PORT}")
    print("Optional integrations: set OPENAI_API_KEY and/or Strava OAuth environment variables.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nQuadfit server stopped.")
    finally:
        server.server_close()
