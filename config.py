import os, yaml

with open('messages.yaml', 'r', encoding='utf-8') as f:
    MESSAGES = yaml.safe_load(f)


class Config:
    ADMIN_ID = int(os.environ['ADMIN_ID'])
    API_TOKEN = os.environ['API_TOKEN']
    BOT_TOKEN = os.environ['BOT_TOKEN']
    URL = os.environ['URL'].rstrip('/')
    SUB_URL = os.environ['SUB_URL'].rstrip('/')
    INBOUND_IDS = os.environ['INBOUND_IDS'].split(",")

    access_denied_error = MESSAGES['error']['access_denied']
    user_not_found_error = MESSAGES['error']['user_not_found']
    unknown_error = MESSAGES['error']['unknown']

    cancel_message = MESSAGES['cancel']
    ban_message = MESSAGES['ban']

    paid_instruction = MESSAGES['paid']['instruction']

    payment_broadcast_text = MESSAGES['payment']['broadcast']['text']
    payment_broadcast_button = MESSAGES['payment']['broadcast']['button']
    payment_broadcast_instruction = MESSAGES['payment']['broadcast']['instruction']
    payment_broadcast_starting = MESSAGES['payment']['broadcast']['starting']
    payment_broadcast_cancel = MESSAGES['payment']['broadcast']['cancel']

    payment_admin_confirmation_request = MESSAGES['payment']['admin']['confirmation']['request']
    payment_admin_approve_button = MESSAGES['payment']['admin']['button']['confirm']
    payment_admin_reject_button = MESSAGES['payment']['admin']['button']['reject']
    payment_admin_confirmation_success = MESSAGES['payment']['admin']['confirmation']['response']['success']
    payment_admin_confirmation_warning = MESSAGES['payment']['admin']['confirmation']['response']['warning']

    payment_client_confirm_button = MESSAGES['payment']['client']['confirm']['button']
    payment_client_confirm_wait_response = MESSAGES['payment']['client']['confirm']['wait_response']
    payment_client_approve_response = MESSAGES['payment']['client']['approve']['response']
    payment_client_approve_text = MESSAGES['payment']['client']['approve']['text']
    payment_client_reject_response = MESSAGES['payment']['client']['reject']['response']
    payment_client_reject_text = MESSAGES['payment']['client']['reject']['text']

    status_expired = MESSAGES['status']['expired']
    status_expires = MESSAGES['status']['expires']
    status_sync_wait = MESSAGES['status']['synchronization']['waiting']
    status_sync_error = MESSAGES['status']['synchronization']['error']
    status_client_table_empty = MESSAGES['status']['client_table']['empty']
    status_client_table_row = MESSAGES['status']['client_table']['row']
    status_message_text = MESSAGES['status']['message']['text']
    status_message_truncate = MESSAGES['status']['message']['truncate']

    broadcast_instruction = MESSAGES['broadcast']['instruction']
    broadcast_starting = MESSAGES['broadcast']['starting']
    broadcast_success = MESSAGES['broadcast']['success']
    broadcast_error = MESSAGES['broadcast']['error']


    database_backup_not_found = MESSAGES['database_backup']['not_found']
    database_backup_failed = MESSAGES['database_backup']['failed']
    database_backup_caption = MESSAGES['database_backup']['caption']

    create_token_wait = MESSAGES['create_token']['wait']
    create_token_error = MESSAGES['create_token']['error']
    create_token_success = MESSAGES['create_token']['success']

    register_admin_button_approve = MESSAGES['register']['admin']['button']['approve']
    register_admin_button_reject = MESSAGES['register']['admin']['button']['reject']
    register_admin_new_client = MESSAGES['register']['admin']['new_client']
    register_client_wait_response = MESSAGES['register']['client']['response']['wait']
    register_client_retry_response = MESSAGES['register']['client']['response']['retry']
    register_client_approve_response = MESSAGES['register']['client']['approve']['response']
    register_client_approve_text = MESSAGES['register']['client']['approve']['text']
    register_client_reject = MESSAGES['register']['client']['reject']

    admin_instruction = MESSAGES['instruction']['admin']
    instruction = MESSAGES['instruction']['common']
