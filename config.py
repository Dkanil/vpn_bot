import yaml

with open('messages.yaml', 'r', encoding='utf-8') as f:
    MESSAGES = yaml.safe_load(f)


class Config:
    access_denied_error = MESSAGES.get('access_denied_error')
    user_not_found_error = MESSAGES.get('user_not_found_error')
    unknown_error = MESSAGES.get('unknown_error')
    cancel_message = MESSAGES.get('cancel_message')
    ban_message = MESSAGES.get('ban_message')

    subscription_expired = MESSAGES.get('subscription_expired')
    subscription_expires = MESSAGES.get('subscription_expires')

    paid_instruction = MESSAGES.get('paid_instruction')

    payment_notification_button = MESSAGES.get('payment_notification_button')
    payment_notification = MESSAGES.get('payment_notification')
    admin_payment_confirmation = MESSAGES.get('admin_payment_confirmation')
    user_payment_confirm_button = MESSAGES.get('user_payment_confirm_button')
    user_payment_confirm_wait_response = MESSAGES.get('user_payment_confirm_wait_response')
    admin_payment_approve_button = MESSAGES.get('admin_payment_approve_button')
    admin_payment_reject_button = MESSAGES.get('admin_payment_reject_button')
    payment_confirmation_approve_response = MESSAGES.get('payment_confirmation_approve_response')
    payment_confirmation_approve = MESSAGES.get('payment_confirmation_approve')
    reject_response = MESSAGES.get('reject_response')
    payment_confirmation_reject = MESSAGES.get('payment_confirmation_reject')

    admin_subscription_update = MESSAGES.get('admin_subscription_update')
    admin_subscription_warning_update = MESSAGES.get('admin_subscription_warning_update')
    subscription_update = MESSAGES.get('subscription_update')

    synchronize_status = MESSAGES.get('synchronize_status')
    empty_users_list = MESSAGES.get('empty_users_list')
    user_row = MESSAGES.get('user_row')
    status_message = MESSAGES.get('status_message')
    truncate_message = MESSAGES.get('truncate_message')
    update_status_error = MESSAGES.get('update_status_error')

    broadcast_instruction = MESSAGES.get('broadcast_instruction')
    broadcast_starting = MESSAGES.get('broadcast_starting')
    broadcast_success = MESSAGES.get('broadcast_success')
    broadcast_error = MESSAGES.get('broadcast_error')

    payment_broadcast_instruction = MESSAGES.get('payment_broadcast_instruction')
    payment_broadcast_cancel = MESSAGES.get('payment_broadcast_cancel')
    payment_broadcast_starting = MESSAGES.get('payment_broadcast_starting')

    database_backup_not_found = MESSAGES.get('database_backup_not_found')
    database_backup_caption = MESSAGES.get('database_backup_caption')
    database_backup_failed = MESSAGES.get('database_backup_failed')

    create_token_wait = MESSAGES.get('create_token_wait')
    create_token_error = MESSAGES.get('create_token_error')
    create_token_success = MESSAGES.get('create_token_success')

    start_command_wait_response = MESSAGES.get('start_command_wait_response')
    start_command_retry_response = MESSAGES.get('start_command_retry_response')
    admin_register_user_approve = MESSAGES.get('admin_register_user_approve')
    admin_register_user_reject = MESSAGES.get('admin_register_user_reject')
    admin_register_request = MESSAGES.get('admin_register_request')
    register_approve_response = MESSAGES.get('register_approve_response')
    register_approve = MESSAGES.get('register_approve')
    register_reject = MESSAGES.get('register_reject')

    admin_instruction = MESSAGES.get('admin_instruction')
    instruction = MESSAGES.get('instruction')
