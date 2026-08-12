import db

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from typing import Callable, Dict, Any, Awaitable
from config import Config


class BannedUserMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")

        if user:
            db.update_username(user.id, user.username)

        if not user or db.is_user_approved(user.id) != -1:
            return await handler(event, data)
        if isinstance(event, Message):
            await event.answer(Config.ban_message)
        return None
