import aiohttp, json, logging

logger = logging.getLogger(__name__)

class AuthManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AuthManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, url: str, api_token: str):
        if self._initialized:
            return

        self.url = url.rstrip('/')
        self.api_token = api_token.strip()
        self.session = None

        self._initialized = True

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            headers = {
                "Accept": "application/json",
                "User-Agent": "vpnBot/1.0",
                "Authorization": f"Bearer {self.api_token}"
            }
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def check_connection(self) -> bool:
        res = await self.api_request("GET", "/panel/api/server/status")
        if res.get("success"):
            logger.info("Successfully connected to 3x-ui by API token!")
            return True
        else:
            logger.error("3x-ui connection error. Check URL and API_TOKEN.")
            return False

    async def api_request(self, method: str, endpoint: str, **kwargs) -> dict:
        session = await self.get_session()
        full_url = f"{self.url}{endpoint}"

        logger.info(f"Request {method} -> {endpoint}")

        try:
            async with session.request(method, full_url, **kwargs) as resp:
                body = await resp.text()

                if resp.status in (401, 403):
                    logger.error(f"{resp.status} Access denied. Token is invalid! Response body: {body[:100]}")
                    return {"success": False, "msg": "AUTH_REQUIRED"}

                if resp.status == 404:
                    logger.error(f"404 Not Found for {full_url}")
                    return {"success": False, "msg": f"404 Not Found: {full_url}"}

                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    logger.error(f"Not JSON in server response: {body[:200]}")
                    return {"success": False, "msg": "INVALID_JSON_RESPONSE"}

        except Exception as e:
            logger.error(f"Error connecting to the 3x-ui panel: {e}")
            return {"success": False, "msg": f"CONNECTION_ERROR: {e}"}
