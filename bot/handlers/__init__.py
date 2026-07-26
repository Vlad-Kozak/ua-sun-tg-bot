from aiogram import Router

from bot.handlers import chat_events, common, membership, mentions, rollcall, settings, tags


def build_router() -> Router:
    """Порядок має значення: mentions ловить довільний текст і має йти останнім.

    Роутери створюються тут, а не на рівні модулів: у aiogram роутер можна
    приєднати лише раз, тож глобальні екземпляри не давали б зібрати
    другий Dispatcher у тому самому процесі (зокрема в тестах).
    """
    router = Router(name="root")
    router.include_router(common.build_router())
    router.include_router(chat_events.build_router())
    router.include_router(tags.build_router())
    router.include_router(membership.build_router())
    router.include_router(rollcall.build_router())
    router.include_router(settings.build_router())
    router.include_router(mentions.build_router())
    return router


__all__ = ["build_router"]
