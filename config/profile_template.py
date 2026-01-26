"""Шаблон профілю (несекретні параметри).

Скопіюй у config/profile_local.py або config/profile_prod.py та зміни значення.
"""

PROFILE_OVERRIDES = {
    "ns": "fxcm_local",
    "redis_url": "redis://127.0.0.1:6379/0",
    "redis_host": "127.0.0.1",
    "redis_port": 6379,
    "metrics_port": 9200,
    "http_port": 8088,
    "ui_lite_host": "127.0.0.1",
    "ui_lite_port": 8089,
    "fxcm_backend": "disabled",
}
