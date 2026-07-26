"""Теги учасників з Bot API 9.5, якого встановлена aiogram ще не знає.

Ключове розрізнення: «поля немає» (Telegram не надсилає) vs «поле порожнє»
(тег справді зняли). Переплутати їх — означає стерти зібрані дані.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram.types import ChatMemberAdministrator, ChatMemberMember, Message

from bot.utils.api_extras import member_tag, read_optional_field, sender_tag

CHAT = {"id": -1001, "type": "supergroup", "title": "Клан"}
USER = {"id": 42, "is_bot": False, "first_name": "Andrusha"}


def make_message(**extra) -> Message:
    payload = {
        "message_id": 1,
        "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": CHAT,
        "from": USER,
        "text": "привіт",
    }
    payload.update(extra)
    return Message.model_validate(payload)


def test_sender_tag_is_read_from_unknown_field():
    present, value = sender_tag(make_message(sender_tag="Enkys Sun"))
    assert (present, value) == (True, "Enkys Sun")


def test_missing_field_is_not_the_same_as_empty():
    """Старий Bot API не надсилає поле — збережений тег чіпати не можна."""
    assert sender_tag(make_message()) == (False, None)


def test_explicit_null_means_tag_was_removed():
    assert sender_tag(make_message(sender_tag=None)) == (True, None)


def test_blank_tag_is_treated_as_removed():
    assert sender_tag(make_message(sender_tag="   ")) == (True, None)


def test_tag_is_trimmed():
    present, value = sender_tag(make_message(sender_tag="  BanGi Sun  "))
    assert (present, value) == (True, "BanGi Sun")


def test_overlong_tag_is_truncated():
    present, value = sender_tag(make_message(sender_tag="x" * 200))
    assert present is True
    assert len(value) == 64


def test_non_string_value_is_ignored():
    present, value = sender_tag(make_message(sender_tag=123))
    assert (present, value) == (True, None)


def test_member_tag_reads_plain_member():
    member = ChatMemberMember.model_validate(
        {"status": "member", "user": USER, "tag": "Wok SUN"}
    )
    assert member_tag(member) == (True, "Wok SUN")


def test_member_tag_falls_back_to_admin_custom_title():
    admin = ChatMemberAdministrator.model_validate(
        {
            "status": "administrator",
            "user": USER,
            "can_be_edited": False,
            "is_anonymous": False,
            "can_manage_chat": True,
            "can_delete_messages": False,
            "can_manage_video_chats": False,
            "can_restrict_members": False,
            "can_promote_members": False,
            "can_change_info": False,
            "can_invite_users": True,
            "can_post_stories": False,
            "can_edit_stories": False,
            "can_delete_stories": False,
            "custom_title": "Agent FDR Sun",
        }
    )
    assert member_tag(admin) == (True, "Agent FDR Sun")


def test_member_without_any_tag():
    member = ChatMemberMember.model_validate({"status": "member", "user": USER})
    assert member_tag(member) == (False, None)


def test_none_source_is_safe():
    assert read_optional_field(None, "sender_tag") == (False, None)
