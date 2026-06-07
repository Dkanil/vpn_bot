import aiohttp
from urllib.parse import urlsplit


class AuthManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AuthManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, url, username, password, api_token=None, two_factor_code=""):
        if self._initialized:
            return

        self.url = url
        self.username = username
        self.password = password
        self.api_token = (api_token or "").strip()
        self.two_factor_code = two_factor_code or ""
        self.session = None

        self._initialized = True

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            jar = aiohttp.CookieJar(unsafe=True)
            headers = {
                "Accept": "application/json",
                "User-Agent": "vpnBot/1.0"
            }
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            self.session = aiohttp.ClientSession(cookie_jar=jar, headers=headers)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def login(self) -> bool:
        if self.api_token:
            return True

        session = await self.get_session()
        login_data = {
            "username": self.username,
            "password": self.password,
            "twoFactorCode": self.two_factor_code
        }

        parts = urlsplit(self.url)
        origin = f"{parts.scheme}://{parts.netloc}"
        login_url = f"{self.url}/login"
        base_headers = {
            "Referer": login_url,
            "Origin": origin,
            "X-Requested-With": "XMLHttpRequest"
        }

        # В некоторых сборках куки сессии выставляются только после GET /login.
        try:
            async with session.get(login_url, headers=base_headers):
                pass
        except Exception:
            pass

        async def login_once(use_json: bool, csrf_token: str = ""):
            kwargs = {"json": login_data} if use_json else {"data": login_data}
            headers = dict(base_headers)
            if csrf_token:
                headers["X-CSRF-Token"] = csrf_token
            async with session.post(login_url, headers=headers, **kwargs) as resp:
                body = await resp.text()
                if resp.status != 200:
                    print(f"AuthManager: Ошибка входа, статус {resp.status}, тело: {body[:300]}")
                    return False
                try:
                    result = await resp.json(content_type=None)
                except Exception:
                    print(f"AuthManager: Некорректный JSON при входе: {body[:300]}")
                    return False
                print("Результат авторизации:", result)
                return result.get("success", False)

        ok = await login_once(use_json=True)
        if ok:
            return True

        ok = await login_once(use_json=False)
        if ok:
            return True

        # CSRF fallback для панелей с жёсткой проверкой middleware.
        csrf_token = ""
        try:
            async with session.get(f"{self.url}/csrf-token", headers=base_headers) as csrf_resp:
                csrf_json = await csrf_resp.json(content_type=None)
                if isinstance(csrf_json, dict):
                    csrf_token = csrf_json.get("obj") or ""
        except Exception:
            csrf_token = ""

        if not csrf_token:
            return False

        ok = await login_once(use_json=True, csrf_token=csrf_token)
        if ok:
            return True
        return await login_once(use_json=False, csrf_token=csrf_token)

    @staticmethod
    def _is_auth_error(result: dict) -> bool:
        msg = str(result.get("msg", "")).upper()
        auth_markers = ("AUTH_REQUIRED", "UNAUTHORIZED", "FORBIDDEN", "LOGIN")
        return any(marker in msg for marker in auth_markers)

    async def api_request(self, method: str, endpoint: str, **kwargs) -> dict:
        session = await self.get_session()
        full_url = f"{self.url}{endpoint}"
        is_panel_api_endpoint = endpoint.startswith("/panel/api/")

        async def make_request():
            print(f"Запрос {method} -> {endpoint}")
            if method == "GET":
                response = session.get(full_url, **kwargs)
            else:
                response = session.post(full_url, **kwargs)
            async with response as resp:
                if resp.status == 404:
                    if is_panel_api_endpoint:
                        return {"success": False, "msg": "AUTH_REQUIRED"}
                    return {"success": False, "msg": f"404 Not Found (проверьте URL): {full_url}"}
                if resp.status in (401, 403):
                    return {"success": False, "msg": "AUTH_REQUIRED"}
                try:
                    return await resp.json()
                except:
                    return {"success": False, "msg": "AUTH_REQUIRED"}

        try:
            result = await make_request()
            if not result.get("success") and self._is_auth_error(result):
                print("AuthManager: Похоже, сессия истекла или её нет. Пробуем авторизоваться...")
                is_logged = await self.login()
                if not is_logged:
                    return {"success": False, "msg": "Ошибка авторизации в панели"}
                result = await make_request()
            return result
        except Exception as e:
            return {"success": False, "msg": f"Ошибка соединения с панелью: {e}"}
