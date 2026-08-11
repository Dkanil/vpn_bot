import asyncio
import os
import secrets
import string
import time
import html
from urllib.parse import quote

import filter
import db_manager
from auth_manager import AuthManager
from config import Config

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


class PaymentAction(CallbackData, prefix="pay"):
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

        db_manager.update_user_from_panel(tg_id, c_date, p_until, group, email)


async def send_admin_individual_notification(tg_id, username, email, status):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=Config.payment_notification_button, callback_data="admin_broadcast_payment")]
    ])

    text = Config.payment_notification.format(tg_id=tg_id,
                                              username=html.escape(username if username else ""),
                                              email=html.escape(email),
                                              status=status)

    await bot.send_message(ADMIN_ID, text, parse_mode="HTML", reply_markup=kb)


async def background_payment_check(auth_manager: AuthManager):
    await asyncio.sleep(10)

    while True:
        try:
            await sync_all_users_from_panel(auth_manager)
            users = db_manager.get_users_for_payment_check()
            now = int(time.time())

            for tg_id, paid_until, notify_level, username, email in users:
                if not paid_until:
                    continue

                left_seconds = paid_until - now

                if left_seconds <= 0 and notify_level < 2:
                    db_manager.set_notify_level(tg_id, 2)
                    await send_admin_individual_notification(tg_id, username, email, Config.subscription_expired)

                elif 0 < left_seconds <= 7 * 24 * 3600 and notify_level < 1:
                    db_manager.set_notify_level(tg_id, 1)
                    await send_admin_individual_notification(tg_id, username, email, Config.subscription_expires)

                elif left_seconds > 7 * 24 * 3600 and notify_level > 0:
                    db_manager.set_notify_level(tg_id, 0)

        except Exception as e:
            print(f"Error processing background_payment_check: {e}")

        await asyncio.sleep(24 * 3600)


@dp.message(Command('paid'))
async def mark_paid_cmd(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    args = command.args
    if not args:
        await message.answer(Config.paid_instruction)
        return

    parts = args.split()
    tg_id = int(parts[0])
    months = int(parts[1]) if len(parts) > 1 else 3

    if db_manager.extend_payment(tg_id, months):
        await message.answer(Config.admin_subscription_update.format(tg_id=tg_id, months=months), parse_mode="HTML")
        try:
            await bot.send_message(tg_id, Config.subscription_update.format(months=months), parse_mode="HTML")
        except Exception:
            await message.answer(Config.admin_subscription_warning_update.format(tg_id=tg_id))
    else:
        await message.answer(Config.user_not_found_error.format(tg_id=tg_id))


@dp.callback_query(F.data == "user_notified_payment")
async def handle_user_payment_notify(call: types.CallbackQuery):
    tg_id = call.from_user.id
    username = call.from_user.username or ""

    await call.message.edit_text(f"{call.message.text}\n\n{Config.user_payment_confirm_wait_response}", parse_mode="HTML")

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=Config.admin_payment_approve_button,
                                 callback_data=PaymentAction(action="approve", user_id=tg_id).pack()),
            InlineKeyboardButton(text=Config.admin_payment_reject_button,
                                 callback_data=PaymentAction(action="reject", user_id=tg_id).pack())
        ]
    ])

    await bot.send_message(
        ADMIN_ID,
        Config.payment_confirmation.format(tg_id=tg_id, username=html.escape(username)),
        parse_mode="HTML",
        reply_markup=admin_kb
    )
    await call.answer()


@dp.callback_query(PaymentAction.filter())
async def handle_admin_payment_decision(call: types.CallbackQuery, callback_data: PaymentAction):
    if call.from_user.id != ADMIN_ID:
        return

    target_id = callback_data.user_id

    if callback_data.action == "approve":
        if db_manager.extend_payment(target_id, 3):
            await call.message.edit_text(f"{call.message.text}\n\n{Config.payment_confirmation_approve_response}", parse_mode="HTML")

            try:
                await bot.send_message(target_id, Config.payment_confirmation_approve, parse_mode="HTML")
            except Exception as e:
                print(f"Error in handle_admin_payment_decision: {e}")
        else:
            await call.message.edit_text(f"{call.message.text}\n\n{Config.unknown_error}")

    elif callback_data.action == "reject":
        await call.message.edit_text(f"{call.message.text}\n\n{Config.reject_response}", parse_mode="HTML")

        try:
            await bot.send_message(target_id, Config.payment_confirmation_reject, parse_mode="HTML")
        except Exception as e:
            print(f"Error in handle_admin_payment_decision: {e}")

    await call.answer()


@dp.message(Command('status'))
async def status_cmd(message: types.Message, auth_manager: AuthManager):
    if message.from_user.id != ADMIN_ID:
        return

    status_msg = await message.answer(Config.synchronize_status)

    try:
        await sync_all_users_from_panel(auth_manager)

        paid, expires, expired = db_manager.get_users_by_payment_status()

        def format_users(users):
            if not users:
                return Config.empty_users_list
            res = ""
            for tg_id, username, email in users:
                res += Config.user_row.format(tg_id=tg_id,
                                              username=html.escape(f"@username" if username else ""),
                                              email=html.escape(email))
            return res

        text = (Config.status_message.format(paid_count=len(paid), paid_list=format_users(paid),
                                             expires_count=len(expires), expires_list=format_users(expires),
                                             expired_count=len(expired), expired_list=format_users(expired)))

        if len(text) > 4000:
            text = text[:4000] + Config.truncate_message

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=Config.payment_notification_button, callback_data="admin_broadcast_payment")]
        ])

        await status_msg.edit_text(text, parse_mode="HTML", reply_markup=kb)

    except Exception as e:
        print(f"Error processing command /status: {e}")
        await status_msg.edit_text(Config.update_status_error)


@dp.callback_query(F.data == "admin_broadcast_payment")
async def ask_payment_message(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await call.message.answer(Config.payment_broadcast_instruction, parse_mode="HTML")
    await state.set_state(BroadcastState.waiting_for_payment_message)
    await call.answer()


@dp.message(Command("cancel"))
async def cancel_fsm(message: types.Message, state: FSMContext):
    if await state.get_state() is not None:
        await state.clear()
        await message.answer(Config.cancel_message)


@dp.message(BroadcastState.waiting_for_payment_message)
async def send_payment_message(message: types.Message, state: FSMContext):
    _, status_0, status_minus_1 = db_manager.get_users_by_payment_status()

    targets = [u[0] for u in status_0 + status_minus_1]

    if not targets:
        await message.answer(Config.payment_broadcast_cancel)
        await state.clear()
        return

    await message.answer(Config.payment_broadcast_starting.format(len(targets)))
    count = 0

    user_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=Config.user_payment_confirm_button, callback_data="user_notified_payment")]
    ])

    for tg_id in targets:
        try:
            await bot.send_message(tg_id, message.text, parse_mode="HTML", reply_markup=user_kb)
            count += 1
            await asyncio.sleep(0.1)
        except Exception:
            pass

    await message.answer(Config.broadcast_success.format(send_count=count, users_count=len(targets)))
    await state.clear()


@dp.message(Command('getdb'))
async def get_db_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    db_path = "users.db"

    if not os.path.exists(db_path):
        await message.reply(Config.database_backup_not_found, parse_mode="HTML")
        return

    try:
        db_file = FSInputFile(db_path, filename="users.db")

        await message.reply_document(
            document=db_file,
            caption=Config.database_backup_caption,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Error sending database backup: {e}")
        await message.reply(Config.database_backup_failed)


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
    log_message = result.get("msg", "API error")

    if result.get("success"):
        print(f"Created new VPN client: {user_email} (inbounds: {target_inbounds})")
        db_manager.update_user_email(tg_id, user_email)
        return sub_id, "Created successfully"

    if "email already in use" in log_message.lower():
        existing_client = await get_client_by_email(user_email, auth_manager)
        if existing_client and existing_client.get("subId"):
            db_manager.update_user_email(tg_id, user_email)
            return existing_client.get("subId"), "Client already exists"

    print(f"Error creating new VPN client {user_email}: {log_message}")
    return None, log_message


async def resolve_existing_client(user_info, auth_manager: AuthManager):
    tg_id = user_info.id
    saved_email = db_manager.get_user_email(tg_id)
    if saved_email:
        client = await get_client_by_email(saved_email, auth_manager)
        if client:
            return client

    legacy_emails = get_user_emails(user_info)
    for candidate_email in legacy_emails:
        client = await get_client_by_email(candidate_email, auth_manager)
        if client:
            actual_email = client.get("email") or candidate_email
            db_manager.update_user_email(tg_id, actual_email)
            print(f"Email '{actual_email}' is fixed in database for user with tg_id={tg_id}")
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
                print(f"Connecting user with email {existing_client['email']} to missing inbounds: {missing_inbounds}")
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
    status = db_manager.is_user_approved(tg_id)
    if status is None:
        db_manager.add_user(tg_id, 0)
        await message.answer(Config.start_command_wait_response)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=Config.admin_register_user_approve,
                    callback_data=AdminAction(action="approve", user_id=tg_id).pack()
                ),
                InlineKeyboardButton(
                    text=Config.admin_register_user_reject,
                    callback_data=AdminAction(action="reject", user_id=tg_id).pack()
                )]
        ])
        username = message.from_user.username
        await bot.send_message(ADMIN_ID, Config.admin_register_request.format(full_name=message.from_user.full_name,
                                                                              username=username if username else "",
                                                                              tg_id=tg_id), reply_markup=kb)
    elif status >= 1:
        await help_cmd(message)
    elif status == 0:
        await message.answer(Config.start_command_retry_response)


@dp.callback_query(AdminAction.filter())
async def handle_admin_action(call: types.CallbackQuery, callback_data: AdminAction):
    if call.from_user.id != ADMIN_ID:
        await call.answer(Config.access_denied_error, show_alert=True)
        return

    target_user_id = callback_data.user_id

    if callback_data.action == "approve":
        db_manager.add_user(target_user_id, 1)
        await call.message.edit_text(f"{call.message.text}\n\n{Config.register_approve_response}", parse_mode="HTML")
        await bot.send_message(target_user_id, Config.register_approve)

    elif callback_data.action == "reject":
        db_manager.add_user(target_user_id, -1)
        await call.message.edit_text(f"{call.message.text}\n\n{Config.reject_response}", parse_mode="HTML")
        await bot.send_message(target_user_id, Config.register_reject)


@dp.message(Command('broadcast'))
async def broadcast_command(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        await message.answer(Config.broadcast_instruction)
        return

    try:
        text = command.args
        users = db_manager.get_vpn_users()

        await message.answer(Config.broadcast_starting.format(users_count=len(users)))
        count = 0
        for user_id in users:
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
                count += 1
                await asyncio.sleep(0.1)
                print(f"Send to user {user_id}")
            except Exception as e:
                print(f"Failed to send to user {user_id}: {e}")

        await message.answer(Config.broadcast_success.format(send_count=count, users_count=len(users)))
    except Exception as e:
        print(f"Error processing broadcast command: {e}")
        await message.answer(Config.broadcast_error)


@dp.message(Command('create_token'))
async def create_token(message: types.Message, auth_manager: AuthManager):
    tg_id = message.from_user.id
    status = db_manager.is_user_approved(tg_id)
    if status is None or status < 1:
        await message.answer(Config.access_denied_error)
        return

    msg = await message.answer(Config.create_token_wait)

    try:
        sub_id = await get_client_credentials(message.from_user, auth_manager)

        sub_url_base = os.getenv('SUB_URL', '').rstrip('/')
        if not sub_url_base:
            raise Exception("SUB_URL value is not set!")

        sub_link = f"{sub_url_base}/{sub_id}"
        text = Config.create_token_success.format(sub_link=sub_link)

        db_manager.add_user(tg_id, 2)
        await msg.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        print(f"Error generating token: {e}")
        await msg.edit_text(Config.create_token_error)


@dp.message(Command('help'))
async def help_cmd(message: types.Message):
    if db_manager.is_user_approved(message.from_user.id) < 1:
        await message.answer(Config.access_denied_error)
        return

    instruction = Config.instruction

    if message.from_user.id == ADMIN_ID:
        instruction = instruction.format(admin_instruction=Config.admin_instruction)
    else:
        instruction = instruction.format(admin_instruction="")

    await message.answer(instruction, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def main():
    db_manager.init_db()
    auth_manager = AuthManager(
        url=os.getenv("URL"),
        api_token=os.getenv("API_TOKEN", ""),
    )
    await auth_manager.check_connection()

    dp.message.middleware(filter.BannedUserMiddleware())
    dp.callback_query.middleware(filter.BannedUserMiddleware())
    asyncio.create_task(background_payment_check(auth_manager))

    try:
        await dp.start_polling(bot, auth_manager=auth_manager)
    finally:
        print("Shutting down...")
        db_manager.close_db()
        await auth_manager.close()
        print("Shutdown successful")


if __name__ == "__main__":
    asyncio.run(main())
