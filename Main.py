import asyncio
import json
import os
import secrets
import string
import uuid
from urllib.parse import quote

import Filter
import DBManager
import AuthManager
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID"))
bot = Bot(token=os.getenv("BOT_TOKEN"))
SUB_URL = os.environ.get("SUB_URL", "")
dp = Dispatcher()
dp["auth_manager"] = None


class AdminAction(CallbackData, prefix="admin"):
    action: str
    user_id: int


def get_user_emails(user_info) -> list[str]:
    emails = []
    if user_info.username:
        emails.append(user_info.username)
    emails.append(f"user{user_info.id}")
    return emails


def generate_sub_id(length: int = 16) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def send_quarterly_payment_notification():
    print("----- Запуск рассылки об оплате... -----")
    try:
        users = DBManager.get_vpn_users()
        text = (
            "🔔 <b>Напоминание об оплате VPN</b>\n\n"
            "Пожалуйста, оплатите подписку на следующие 3 месяца.\n\n"
            "ℹ️ <i>Реквизиты для оплаты:</i>\n"
            f"По номеру телефона: {os.getenv('PAYMENT')}\n"
        )

        count = 0
        for user_id in users:
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
                count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Не удалось отправить юзеру {user_id}: {e}")

        print(f"✅ Рассылка завершена. Отправлено: {count}")
        await bot.send_message(ADMIN_ID, f"📢 Автоматическая рассылка проведена.\nДоставлено сообщений: {count}")

    except Exception as e:
        print(f"❌ Ошибка при рассылке: {e}")


async def add_vpn_client(user_info, auth_manager: AuthManager.AuthManager):
    user_email = get_user_emails(user_info)[0]
    tg_id = user_info.id
    client_uuid = str(uuid.uuid4())
    sub_id = generate_sub_id()
    new_client = {
        "id": client_uuid,
        "uuid": client_uuid,
        "email": user_email,
        "limitIp": 5,
        "totalGB": 0,
        "expiryTime": 0,
        "enable": True,
        "tgId": tg_id,
        "subId": sub_id,
        "reset": 0,
    }

    payload = {
        "client": new_client,
        "inboundIds": [int(os.getenv("CONNECTION_ID"))]
    }
    connection_id = int(os.getenv("CONNECTION_ID"))
    legacy_payload = {
        "id": connection_id,
        "settings": json.dumps({"clients": [new_client]})
    }
    add_attempts = [
        ("/panel/api/clients/add", {"json": payload}),
        ("/panel/api/inbounds/addClient", {"json": legacy_payload}),
        (f"/panel/api/inbounds/addClient/{connection_id}", {"json": legacy_payload}),
        ("/xui/API/inbounds/addClient", {"json": legacy_payload}),
        (f"/xui/API/inbounds/addClient/{connection_id}", {"json": legacy_payload}),
    ]

    result = {"success": False, "msg": "Не удалось добавить клиента"}
    for endpoint, kwargs in add_attempts:
        result = await auth_manager.api_request("POST", endpoint, **kwargs)
        msg = result.get("msg", "Ошибка API")
        if result.get("success"):
            break
        if "404 Not Found" in msg:
            print(f"Endpoint {endpoint} недоступен, пробуем следующий вариант")
            continue
        break

    if result.get("success"):
        for attempt in range(5):
            created_client = await get_client_by_email(user_email, auth_manager)
            if created_client:
                created_uuid = created_client.get("uuid") or created_client.get("id")
                created_sub_id = created_client.get("subId")
                if created_uuid and created_sub_id:
                    print(f"Сгенерирован новый клиент VPN: {user_email}")
                    return created_uuid, created_sub_id, "Успешно создано"

            if attempt < 4:
                await asyncio.sleep(0.5)

        print(f"Клиент {user_email} создан, но не удалось проверить его через /clients/get; используем сгенерированные uuid/subId")
        return client_uuid, sub_id, "Успешно создано"
    else:
        if "already" in msg.lower() or "duplicate" in msg.lower() or "exist" in msg.lower():
            existing_client = await get_client_by_email(user_email, auth_manager)
            if existing_client:
                created_uuid = existing_client.get("uuid") or existing_client.get("id")
                created_sub_id = existing_client.get("subId")
                if created_uuid and created_sub_id:
                    print(f"Клиент VPN уже существует, используем его: {user_email}")
                    return created_uuid, created_sub_id, "Клиент уже существовал"

        print("Ошибка при добавлении клиента VPN:", msg)
        return None, None, msg


async def resolve_existing_client(user_info, auth_manager: AuthManager.AuthManager):
    for candidate_email in get_user_emails(user_info):
        existing_client = await get_client_by_email(candidate_email, auth_manager)
        if existing_client:
            return existing_client
    return None


async def get_client_credentials(user_info, auth_manager: AuthManager.AuthManager):
    existing_client = await resolve_existing_client(user_info, auth_manager)
    if existing_client:
        client_uuid = existing_client.get("uuid") or existing_client.get("id")
        sub_id = existing_client.get("subId", "")
        if client_uuid and sub_id:
            return client_uuid, sub_id
        print(f"Клиент найден, но не хватает uuid/subId: {existing_client}")

    client_uuid, sub_id, msg = await add_vpn_client(user_info, auth_manager)
    if not client_uuid or not sub_id:
        raise Exception(msg)
    return client_uuid, sub_id


async def get_client_by_email(email: str, auth_manager: AuthManager.AuthManager):
    response = await auth_manager.api_request("GET", f"/panel/api/clients/get/{quote(email, safe='')}")
    if not response.get("success"):
        return None
    obj = response.get("obj")
    if not isinstance(obj, dict):
        return obj
    client = obj.get("client")
    if isinstance(client, dict):
        normalized = dict(client)
        normalized["inboundIds"] = obj.get("inboundIds", [])
        return normalized
    return obj


async def get_client_link_by_subid(sub_id: str, auth_manager: AuthManager.AuthManager):
    response = await auth_manager.api_request(
        "GET",
        f"/panel/api/clients/subLinks/{quote(sub_id, safe='')}"
    )
    if not response.get("success"):
        return None

    links = response.get("obj")
    if not isinstance(links, list) or not links:
        return None

    for link in links:
        if isinstance(link, str) and link.startswith("vless://"):
            return link
    return links[0] if isinstance(links[0], str) else None


@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    tg_id = message.from_user.id
    status = DBManager.is_user_approved(tg_id)
    if status is None:
        DBManager.add_user(tg_id, 0)
        await message.answer("Заявка отправлена администратору. Ожидайте.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Разрешить",
                    callback_data=AdminAction(action="approve", user_id=tg_id).pack()
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=AdminAction(action="reject", user_id=tg_id).pack()
                )]
        ])
        await bot.send_message(ADMIN_ID,
                               f"Новый пользователь: {message.from_user.full_name} (@{message.from_user.username})\nID: {tg_id}",
                               reply_markup=kb)
    elif status >= 1:
        await help_cmd(message)
    elif status == 0:
        await message.answer("Ваша заявка на рассмотрении администратора. Ожидайте.")


@dp.callback_query(AdminAction.filter())
async def handle_admin_action(call: types.CallbackQuery, callback_data: AdminAction):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Куда лезешь?!", show_alert=True)
        return

    target_user_id = callback_data.user_id

    if callback_data.action == "approve":
        DBManager.add_user(target_user_id, 1)
        await call.message.edit_text(f"{call.message.text}\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")
        await bot.send_message(target_user_id,
                               "🎉 Администратор одобрил доступ!\nВведите /help для получения инструкций.")

    elif callback_data.action == "reject":
        DBManager.add_user(target_user_id, -1)
        await call.message.edit_text(f"{call.message.text}\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
        await bot.send_message(target_user_id, "К сожалению, вам отказано в доступе.")

@dp.message(Command('broadcast'))
async def broadcast_command(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer("Использование: /broadcast <текст сообщения>")
        return

    try:
        text = command.args
        users = DBManager.get_vpn_users()

        await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
        count = 0
        for user_id in users:
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
                count += 1
                await asyncio.sleep(0.1)
                print(f"Отправлено юзеру {user_id}")
            except Exception as e:
                print(f"Не удалось отправить юзеру {user_id}: {e}")

        await message.answer(f"✅ Рассылка завершена.\nУспешно доставлено: {count} из {len(users)}")
    except Exception as e:
        print(f"Ошибка при рассылке: {e}")
        await message.answer("❌ Произошла ошибка при рассылке.")

@dp.message(Command('create_token'))
async def create_token(message: types.Message, auth_manager: AuthManager.AuthManager):
    tg_id = message.from_user.id
    status = DBManager.is_user_approved(tg_id)
    if status is None or status < 1:
        await message.answer("У вас нет доступа.")
        return

    await message.answer("Получение токена, подождите...")

    try:
        client_uuid, sub_id = await get_client_credentials(message.from_user, auth_manager)

        vless_link = await get_client_link_by_subid(sub_id, auth_manager)
        if not vless_link:
            raise Exception("Не удалось получить ссылку клиента через /panel/api/clients/subLinks/{subId}")



        sub_link = f"{os.getenv('SUB_URL')}/{sub_id}"
        text = (
                "✅ <b>Ваш персональный ключ создан!</b>\n" +
                f"<a href='{sub_link}'>Проверить статус токена / получить токен для другого протокола</a>\n\n" +
                "Ваш токен:\n" +
                f"<pre>{vless_link}</pre>"
        )
        DBManager.add_user(tg_id, 2)
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print(f"Ошибка при создании токена: {e}")
        await message.answer("❌ Ошибка при создании токена")


@dp.message(Command('help'))
async def help_cmd(message: types.Message):
    if DBManager.is_user_approved(message.from_user.id) < 1:
        await message.answer("У вас нет доступа.")
        return

    await message.answer("""<b>Список доступных команд:</b>
/create_token - получить VPN токен
/help - помощь


<b>Инструкция по установке:</b>

1️⃣ Получить свой токен с помощью команды /create_token

2️⃣ Скачать и установить клиент для VPN:
    - <b>Windows:</b> <a href='https://v2rayn.2dust.link'>Скачать v2rayN</a> 
        (Необходимо загрузить <code>v2rayN-windows-64.zip</code>) 
        Скачанный архив распаковать и запустить <code>v2rayN.exe</code>
        (Если с официального сайта грузит медленно, то можно скачать с GitHub тот же файл: <a href='https://github.com/2dust/v2rayN/releases'>GitHub</a>)
    - <b>Android:</b> <a href='https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box&hl=ru'>Скачать V2Box (Google Play)</a>
    - <b>iPhone (iOS), macOs:</b> <a href='https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690'>Скачать V2Box (App Store)</a>

3️⃣ Скопировать полученный токен и вставить его в клиент для подключения к VPN.
📱 <b>На телефоне и macOS (V2Box):</b> 
Перейдите на вкладку <i>«Конфигурации»</i> (снизу) ➔ нажмите <b>«+»</b> (сверху) ➔ выберите <i>«Импортировать v2ray из буфера обмена»</i>.

💻 <b>На компьютере (v2rayN):</b> 
Откройте программу с правами администратора ➔ нажмите <code>Ctrl + V</code> в центре окна ➔ в самом низу окна выберите <i>«Clear system proxy»</i> ➔ включите тумблер <i>«Enable Tun»</i>.

4️⃣ <i>Дополнительно:</i> Вы можете настроить маршрутизацию, добавив определенные сайты (например, Госуслуги или банки) в список исключений, чтобы они работали без VPN."""
                         , parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def main():
    DBManager.init_db()
    auth_manager = AuthManager.AuthManager(
        url=os.getenv("URL"),
        api_token=os.getenv("API_TOKEN", ""),
    )
    await auth_manager.check_connection()

    dp.message.middleware(Filter.BannedUserMiddleware())
    dp.callback_query.middleware(Filter.BannedUserMiddleware())

    # scheduler = AsyncIOScheduler()
    # scheduler.add_job(
    #     send_quarterly_payment_notification,
    #     trigger='cron',
    #     month='3,6,9,12',
    #     day='5',
    #     hour='12',
    #     minute='00',
    # )
    # scheduler.start()
    try:
        await dp.start_polling(bot, auth_manager=auth_manager)
    finally:
        print("Выключение бота...")
        # scheduler.shutdown()
        DBManager.close_db()
        await auth_manager.close()
        print("Работа бота завершена.")


if __name__ == "__main__":
    asyncio.run(main())
