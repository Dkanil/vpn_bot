import asyncio
import os
import secrets
import string
import time
from urllib.parse import quote

import Filter
import DBManager
from AuthManager import AuthManager

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID"))
bot = Bot(token=os.getenv("BOT_TOKEN"))
SUB_URL = os.environ.get("SUB_URL", "")
dp = Dispatcher()
dp["auth_manager"] = None


class BroadcastState(StatesGroup):
    waiting_for_payment_message = State()


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


async def sync_all_users_from_panel(auth_manager: AuthManager):
    res = await auth_manager.api_request("GET", "/panel/api/clients/list")
    if not res.get("success"):
        return

    clients = res.get("obj", [])
    now = int(time.time())

    for c in clients:
        tg_id_raw = c.get("tgId")
        email = c.get("email")
        if not tg_id_raw or not email:
            continue

        try:
            tg_id = int(tg_id_raw)
        except ValueError:
            continue

        created = c.get("createdAt") or (now * 1000)
        c_date = int(created) // 1000
        p_until = c_date + (90 * 24 * 3600)
        group = c.get("group") or c.get("group_name") or ""

        DBManager.update_user_from_panel(tg_id, c_date, p_until, group, email)


async def send_admin_individual_notification(tg_id, status_text):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Сделать рассылку должникам", callback_data="admin_broadcast_payment")]
    ])
    text = (
        f"🔔 <b>Подошел срок оплаты!</b>\n\n"
        f"👤 <b>Пользователь:</b> <a href='tg://user?id={tg_id}'>{tg_id}</a>\n"
        f"📊 <b>Статус:</b> {status_text}\n\n"
        f"Хотите отправить рассылку с напоминанием?"
    )
    await bot.send_message(ADMIN_ID, text, parse_mode="HTML", reply_markup=kb)


async def background_payment_check(auth_manager: AuthManager):
    while True:
        try:
            await sync_all_users_from_panel(auth_manager)
            users = DBManager.get_users_for_payment_check()
            now = int(time.time())

            for tg_id, paid_until, notify_level in users:
                if not paid_until:
                    continue

                left_seconds = paid_until - now

                if left_seconds <= 0 and notify_level < 2:
                    DBManager.set_notify_level(tg_id, 2)
                    await send_admin_individual_notification(tg_id, "🔴 ПРОСРОЧЕНО (< 0 дней)")

                elif 0 < left_seconds <= 7 * 24 * 3600 and notify_level < 1:
                    DBManager.set_notify_level(tg_id, 1)
                    await send_admin_individual_notification(tg_id, "🟡 ИСТЕКАЕТ (< 7 дней)")

                elif left_seconds > 7 * 24 * 3600 and notify_level > 0:
                    DBManager.set_notify_level(tg_id, 0)

        except Exception as e:
            print(f"Ошибка в background_payment_check: {e}")

        await asyncio.sleep(24 * 3600)


@dp.message(Command('paid'))
async def mark_paid_cmd(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    args = command.args
    if not args:
        await message.answer(
            "Использование: /paid <tg_id> [кол-во месяцев (по умолчанию 3)]\nПример: /paid 123456789 3")
        return

    parts = args.split()
    tg_id = int(parts[0])
    months = int(parts[1]) if len(parts) > 1 else 3

    if DBManager.extend_payment(tg_id, months):
        await message.answer(f"✅ Подписка для юзера <code>{tg_id}</code> продлена на {months} мес.", parse_mode="HTML")
        try:
            await bot.send_message(tg_id,
                                   f"🎉 <b>Спасибо за оплату!</b>\nВаша подписка на VPN успешно продлена на {months} мес.",
                                   parse_mode="HTML")
        except Exception:
            await message.answer("⚠️ Подписка продлена, но юзер заблокировал бота.")
    else:
        await message.answer("❌ Пользователь не найден.")


@dp.message(Command('status'))
async def status_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    status_1, status_0, status_minus_1 = DBManager.get_users_by_payment_status()
    text = (
        "📊 <b>Статус оплат (без учета группы private):</b>\n\n"
        f"🟢 <b>Оплачено:</b> {len(status_1)} чел.\n"
        f"🟡 <b>Истекает (менее 7 дней):</b> {len(status_0)} чел.\n"
        f"🔴 <b>Просрочено:</b> {len(status_minus_1)} чел.\n\n"
        "Для продления подписки: <code>/paid &lt;tg_id&gt; [мес]</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Написать должникам", callback_data="admin_broadcast_payment")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "admin_broadcast_payment")
async def ask_payment_message(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await call.message.answer(
        "📝 <b>Введите текст сообщения.</b>\n"
        "Оно будет отправлено всем, у кого статус оплаты 🟡 и 🔴 (исключая группу private).\n\n"
        "<i>Для отмены введите /cancel</i>", parse_mode="HTML"
    )
    await state.set_state(BroadcastState.waiting_for_payment_message)
    await call.answer()


@dp.message(Command("cancel"))
async def cancel_fsm(message: types.Message, state: FSMContext):
    if await state.get_state() is not None:
        await state.clear()
        await message.answer("Действие отменено.")


@dp.message(BroadcastState.waiting_for_payment_message)
async def send_payment_message(message: types.Message, state: FSMContext):
    text = message.text
    _, status_0, status_minus_1 = DBManager.get_users_by_payment_status()
    targets = status_0 + status_minus_1

    if not targets:
        await message.answer("Никто не должен оплату. Рассылка отменена.")
        await state.clear()
        return

    await message.answer(f"⏳ Начинаю рассылку для {len(targets)} пользователей...")
    count = 0
    for tg_id in targets:
        try:
            await bot.send_message(tg_id, text, parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.1)
        except Exception:
            pass

    await message.answer(f"✅ Рассылка завершена. Успешно доставлено: {count} из {len(targets)}")
    await state.clear()


@dp.message(Command('getdb'))
async def get_db_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    db_path = "users.db"

    if not os.path.exists(db_path):
        await message.reply("❌ Файл базы данных <code>users.db</code> не найден на сервере.", parse_mode="HTML")
        return

    try:
        db_file = FSInputFile(db_path, filename="users.db")

        await message.reply_document(
            document=db_file,
            caption="📦 <b>Резервная копия локальной базы данных бота</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка при отправке базы данных: {e}")
        await message.reply(f"❌ Не удалось отправить файл базы данных. Ошибка: {e}")


async def add_vpn_client(user_info, auth_manager: AuthManager, target_inbounds: list[int]):
    user_email = get_user_emails(user_info)[0]
    tg_id = user_info.id
    sub_id = generate_sub_id()
    new_client = {
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
        "inboundIds": target_inbounds
    }

    result = await auth_manager.api_request("POST", "/panel/api/clients/add", json=payload)
    msg = result.get("msg", "Ошибка API")

    if result.get("success"):
        print(f"Сгенерирован новый клиент VPN: {user_email} (inbounds: {target_inbounds})")
        DBManager.update_user_email(tg_id, user_email)
        return sub_id, "Успешно создано"

    if "email already in use" in msg.lower():
        existing_client = await get_client_by_email(user_email, auth_manager)
        if existing_client and existing_client.get("subId"):
            DBManager.update_user_email(tg_id, user_email)
            return existing_client.get("subId"), "Клиент уже существовал"

    print(f"Ошибка при добавлении клиента VPN {user_email}: {msg}")
    return None, msg


async def resolve_existing_client(user_info, auth_manager: AuthManager):
    tg_id = user_info.id
    saved_email = DBManager.get_user_email(tg_id)
    if saved_email:
        client = await get_client_by_email(saved_email, auth_manager)
        if client:
            return client

    legacy_emails = get_user_emails(user_info)
    for candidate_email in legacy_emails:
        client = await get_client_by_email(candidate_email, auth_manager)
        if client:
            actual_email = client.get("email") or candidate_email
            DBManager.update_user_email(tg_id, actual_email)
            print(f"Локально зафиксирован email '{actual_email}' для юзера {tg_id}")
            return client
    return None


async def get_client_credentials(user_info, auth_manager: AuthManager):
    target_inbounds = [int(i.strip()) for i in os.getenv("INBOUND_IDS").split(",") if i.strip().isdigit()]

    existing_client = await resolve_existing_client(user_info, auth_manager)
    if existing_client:
        sub_id = existing_client.get("subId", "")
        if sub_id:
            existing_inbounds = existing_client.get("inboundIds", [])
            missing_inbounds = list(set(target_inbounds) - set(existing_inbounds))

            if missing_inbounds:
                print(f"Привязываем клиента {existing_client['email']} к новым протоколам: {missing_inbounds}")
                await auth_manager.api_request(
                    "POST",
                    f"/panel/api/clients/{quote(existing_client['email'], safe='')}/attach",
                    json={"inboundIds": missing_inbounds}
                )
            return sub_id

    sub_id, msg = await add_vpn_client(user_info, auth_manager, target_inbounds)
    if not sub_id:
        raise Exception(msg)
    return sub_id


async def get_client_by_email(email: str, auth_manager: AuthManager):
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

    msg = await message.answer("Получение токена, подождите...")

    try:
        sub_id = await get_client_credentials(message.from_user, auth_manager)

        sub_url_base = os.getenv('SUB_URL', '').rstrip('/')
        if not sub_url_base:
            raise Exception("Не задана переменная SUB_URL в настройках сервера")

        sub_link = f"{sub_url_base}/{sub_id}"

        text = (
            "✅ <b>Ваша персональная подписка готова!</b>\n\n"
            "По этой ссылке ваше приложение автоматически загрузит все доступные протоколы.\n\n"
            "🔗 <b>Ваша ссылка подписки:</b>\n"
            f"<pre>{sub_link}</pre>\n\n"
            "<i>Скопируйте её и добавьте в приложение (v2rayN, V2Box, Happ) через опцию <b>'Добавить подписку'</b></i>"
            "Подробная инструкция по команде /help"
        )
        DBManager.add_user(tg_id, 2)
        await msg.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        print(f"Ошибка при создании токена: {e}")
        await msg.edit_text("❌ Ошибка при создании токена")


@dp.message(Command('help'))
async def help_cmd(message: types.Message):
    if DBManager.is_user_approved(message.from_user.id) < 1:
        await message.answer("У вас нет доступа.")
        return

    await message.answer("""<b>Список доступных команд:</b>
/create_token - получить ссылку на VPN подписку
/help - помощь


<b>Инструкция по установке:</b>

1️⃣ Получить свою персональную ссылку подписки с помощью команды /create_token

2️⃣ Скачать и установить клиент для VPN:
    - <b>Windows:</b> <a href='https://v2rayn.2dust.link'>Скачать v2rayN</a> 
        (Необходимо загрузить <code>v2rayN-windows-64.zip</code>) 
        Скачанный архив распаковать и запустить <code>v2rayN.exe</code>
        (Если с официального сайта грузит медленно, то можно скачать с GitHub тот же файл: <a href='https://github.com/2dust/v2rayN/releases'>GitHub</a>)
    - <b>Android:</b> <a href='https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box&hl=ru'>Скачать V2Box (Google Play)</a>
    - <b>iPhone (iOS), macOS:</b> <a href='https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690'>Скачать V2Box (App Store)</a>

3️⃣ Скопировать полученную ссылку подписки и добавить её в клиент.
📱 <b>На телефоне и macOS (V2Box):</b> 
Перейдите на вкладку <i>«Конфигурации»</i> (снизу) ➔ Нажмите <b>«+»</b> (сверху) ➔ Выберите <i>«Добавить подписку»</i> ➔ Задайте любое имя в поле "Название" (например, <code>dan4ek VPN</code>) и вставьте скопированную ссылку подписки в поле URL.

⚡ <b>Как запустить и выбрать рабочий протокол:</b> 
После добавления подписки нажмите на кнопку <b>«Пинг»</b> (кнопка в правом верхнем углу «Пинг всех»). У каждого протокола в списке появится значение задержки в миллисекундах (например, <code>120 ms</code>). Выберите тот вариант, где пинг минимальный и горит зеленым цветом (просто нажмите на него), а затем нажмите подключиться.

💻 <b>На компьютере (v2rayN):</b> 
Откройте программу с правами администратора ➔ Нажмите <b>«+»</b> (сверху) ➔ Задайте любое имя в поле Remarks (например, <code>dan4ek VPN</code>) и вставьте скопированную ссылку подписки в поле URL ➔ Включите тумблер Enable update и установите в этой же строке значение 600. 
Нажмите сверху <code>Subscription group</code> ➔ <code>Update subscription without proxy</code>. 

⚡ <b>Как протестировать и выбрать сервер:</b> 
Нажмите на кнопку оо значком молнии, либо спидометра. В столбце <i>«Delay»</i> (Задержка) появятся цифры в миллисекундах, а в столбце Speed текущая скорость. 
Выберите любой рабочий сервер с наименьшим пингом (где отображаются цифры, а не -1) и наибольшей скоростью, кликните на него дважды, чтобы выбрать его. 
В самом низу окна выберите <i>«Clear system proxy»</i> ➔ включите тумблер <i>«Enable Tun»</i>.

4️⃣ <i>Дополнительно:</i> Вы можете настроить маршрутизацию, добавив определенные сайты (например, Госуслуги или банки) в список исключений, чтобы они работали напрямую без VPN."""
                         , parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def main():
    DBManager.init_db()
    auth_manager = AuthManager(
        url=os.getenv("URL"),
        api_token=os.getenv("API_TOKEN", ""),
    )
    await auth_manager.check_connection()

    dp.message.middleware(Filter.BannedUserMiddleware())
    dp.callback_query.middleware(Filter.BannedUserMiddleware())
    asyncio.create_task(background_payment_check(auth_manager))

    try:
        await dp.start_polling(bot, auth_manager=auth_manager)
    finally:
        print("Выключение бота...")
        DBManager.close_db()
        await auth_manager.close()
        print("Работа бота завершена.")


if __name__ == "__main__":
    asyncio.run(main())
