"""Шаблон секретів для FXCM (НЕ комітити з реальними значеннями).

Скопіюй у config/secrets_local.py або config/secrets_prod.py і заповни.
"""

FXCM_USERNAME = "CHANGE_ME"
FXCM_PASSWORD = "CHANGE_ME"

# HMAC auth для команд (не комітити реальні значення)
COMMAND_AUTH_DEFAULT_KID = "k1"
COMMAND_AUTH_SECRETS = {
    "k1": "CHANGE_ME",
}
