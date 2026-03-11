import aiohttp


class AuthManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AuthManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, url, username, password):
        if self._initialized:
            return

        self.url = url
        self.username = username
        self.password = password
        self.session = None

        self._initialized = True

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            jar = aiohttp.CookieJar(unsafe=True)
            self.session = aiohttp.ClientSession(cookie_jar=jar)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def login(self) -> bool:
        session = await self.get_session()
        login_data = {"username": self.username, "password": self.password}
        async with session.post(f"{self.url}/login", data=login_data) as resp:
            if resp.status != 200:
                print(f"AuthManager: Ошибка входа, статус {resp.status}")
                return False
            try:
                result = await resp.json()
            except Exception as e:
                text = await resp.text()
                print(f"Ошибка авторизации {e}: Получен ответ от сервера: {text}")
                return False
            print("Результат авторизации:", result)
            return result.get("success", False)

    async def api_request(self, method: str, endpoint: str, **kwargs) -> dict:
        session = await self.get_session()
        full_url = f"{self.url}{endpoint}"

        async def make_request():
            print(f"Запрос {method} -> {endpoint}")
            if method == "GET":
                response = session.get(full_url, **kwargs)
            else:
                response = session.post(full_url, **kwargs)
            async with response as resp:
                if resp.status == 404:
                    return {"success": False, "msg": f"404 Not Found (проверьте URL): {full_url}"}
                try:
                    return await resp.json()
                except:
                    return {"success": False, "msg": "AUTH_REQUIRED"}

        try:
            result = await make_request()
            if not result.get("success"):
                print("AuthManager: Похоже, сессия истекла или её нет. Пробуем авторизоваться...")
                is_logged = await self.login()
                if not is_logged:
                    return {"success": False, "msg": "Ошибка авторизации в панели"}
                result = await make_request()
            return result
        except Exception as e:
            return {"success": False, "msg": f"Ошибка соединения с панелью: {e}"}
