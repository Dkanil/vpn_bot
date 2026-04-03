import asyncio
import urllib
import uuid
import json
import os

import Filter
import DBManager
import AuthManager
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID"))
URL = os.getenv("URL")
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
dp["auth_manager"] = None


class AdminAction(CallbackData, prefix="admin"):
    action: str
    user_id: int


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


async def add_vpn_client(user_info, auth_manager: AuthManager):
    if user_info.username:
        user_email = user_info.username
    else:
        user_email = f"user{user_info.id}"
    tg_id = user_info.id
    client_uuid = str(uuid.uuid4())
    sub_id = str(uuid.uuid4())
    new_client = {
        "id": client_uuid,
        "flow": "",
        "email": user_email,
        "limitIp": 5,
        "totalGB": 0,
        "expiryTime": 0,
        "enable": True,
        "tgId": str(tg_id),
        "subId": sub_id
    }

    payload = {
        "id": int(os.getenv("CONNECTION_ID")),
        "settings": json.dumps({"clients": [new_client]})
    }
    result = await auth_manager.api_request("POST", "/panel/api/inbounds/addClient", json=payload)
    if result.get("success"):
        print(f"Сгенерирован новый клиент VPN: {user_email}")
        return client_uuid, sub_id, "Успешно создано"
    else:
        print("Ошибка при добавлении клиента VPN:", result.get("msg", "Нет сообщения об ошибке"))
        return None, None, result.get("msg", "Ошибка API")


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
async def create_token(message: types.Message, auth_manager: AuthManager):
    tg_id = message.from_user.id
    status = DBManager.is_user_approved(tg_id)
    if status is None or status < 1:
        await message.answer("У вас нет доступа.")
        return

    await message.answer("Получение токена, подождите...")

    try:
        response = await auth_manager.api_request("GET", f"/panel/api/inbounds/get/{os.getenv('CONNECTION_ID')}")
        if not response.get("success"):
            raise Exception(f"API Error: {response.get('msg')}")

        inbound_obj = response.get("obj")
        settings = json.loads(inbound_obj.get("settings"))

        if status == 2:
            existing_client = None
            for client in settings.get("clients", []):
                if str(client.get("tgId")) == str(tg_id):
                    existing_client = client
                    break
            if existing_client is None:
                raise Exception("Клиент не найден, хотя статус 2. Это может быть ошибкой в базе данных.")
            client_uuid = existing_client["id"]
            sub_id = existing_client.get("subId", "")
            email = existing_client["email"]
        else:
            client_uuid, sub_id, msg = await add_vpn_client(message.from_user, auth_manager)
            if message.from_user.username:
                email = message.from_user.username
            else:
                email = f"user{message.from_user.id}"

        if not client_uuid:
            await message.answer("❌ Ошибка при создании токена")
            return

        stream_settings = json.loads(inbound_obj.get("streamSettings"))
        net_type = stream_settings.get("network", "xhttp")
        security = stream_settings.get("security", "none")
        params = {
            "type": net_type,
            "security": security,
            "encryption": "none"
        }
        if security == "reality":
            reality_settings = stream_settings.get("realitySettings", {})
            settings_inner = reality_settings.get("settings", {})
            params["pbk"] = settings_inner.get("publicKey")
            params["fp"] = settings_inner.get("fingerprint", "firefox")
            sids = reality_settings.get("shortIds", [])
            params["sid"] = sids[0]
            server_names = reality_settings.get("serverNames", [])
            params["sni"] = server_names[0]
            params["spx"] = "/"
            params["pqv"] = settings_inner.get("mldsa65Verify")
        else:
            raise Exception(f"Неизвестный тип безопасности: {response.get('msg')}")
        if net_type == "xhttp":
            xhttp = stream_settings.get("xhttpSettings", {})
            params["path"] = xhttp.get("path", "/")
            params["host"] = xhttp.get("host", "")
            params["mode"] = xhttp.get("mode", "auto")
        else:
            raise Exception(f"Неизвестный тип сети: {response.get('msg')}")

        query_string = urllib.parse.urlencode(params)
        vless_link = f"vless://{client_uuid}@{os.getenv('SERVER_IP')}:{inbound_obj.get('port')}?{query_string}#{email}"
        sub_link = f"http://{os.getenv('SERVER_IP')}:2096/sub/{sub_id}"
        text = (
                "✅ <b>Ваш персональный ключ создан!</b>\n" +
                f"<a href='{sub_link}'>Проверить статус токена</a>\n\n" +
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
    auth_manager = AuthManager.AuthManager(URL, os.getenv("PANEL_USERNAME"), os.getenv("PANEL_PASSWORD"))
    dp.message.middleware(Filter.BannedUserMiddleware())
    dp.callback_query.middleware(Filter.BannedUserMiddleware())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_quarterly_payment_notification,
        trigger='cron',
        month='3,6,9,12',
        day='5',
        hour='12',
        minute='00',
    )
    scheduler.start()
    try:
        await dp.start_polling(bot, auth_manager=auth_manager)
    finally:
        print("Выключение бота...")
        scheduler.shutdown()
        DBManager.close_db()
        await auth_manager.close()
        print("Работа бота завершена.")


if __name__ == "__main__":
    asyncio.run(main())
