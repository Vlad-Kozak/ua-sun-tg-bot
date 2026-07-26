from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bot.utils.time import utcnow


class Base(DeclarativeBase):
    pass


class Chat(Base):
    """Група, у яку додали бота. Налаштування живуть тут, а не глобально."""

    __tablename__ = "chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[Optional[str]] = mapped_column(String(256), default=None)

    all_policy: Mapped[str] = mapped_column(String(16), default="admins")
    tag_policy: Mapped[str] = mapped_column(String(16), default="admins")
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=600)

    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Kyiv")
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_start: Mapped[int] = mapped_column(Integer, default=23)
    quiet_end: Mapped[int] = mapped_column(Integer, default=8)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    members: Mapped[List[ChatMember]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
    tags: Mapped[List[Tag]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class User(Base):
    """Профіль користувача, спільний для всіх чатів."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    last_name: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    username: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ChatMember(Base):
    """Хто перебуває в якому чаті. Наповнюється трекером і подіями chat_member."""

    __tablename__ = "chat_members"

    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.chat_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Користувач сам виключив себе з @all через /mute_me.
    muted_from_all: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=None
    )
    #: Рідний тег Telegram (Bot API 9.5): `sender_tag` повідомлення або
    #: `tag`/`custom_title` учасника. NULL — тега немає або Telegram його ще
    #: не надсилає цьому боту.
    telegram_tag: Mapped[Optional[str]] = mapped_column(String(64), default=None)

    chat: Mapped[Chat] = relationship(back_populates="members")
    user: Mapped[User] = relationship()

    __table_args__ = (
        Index("ix_chat_members_active", "chat_id", "is_active"),
    )


class Tag(Base):
    """Іменований тег у межах одного чату."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.chat_id", ondelete="CASCADE"), nullable=False
    )
    #: Назва в оригінальному регістрі — показуємо її користувачам.
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Нормалізований ключ для пошуку й унікальності.
    name_lower: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chat: Mapped[Chat] = relationship(back_populates="tags")
    members: Mapped[List[TagMember]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("chat_id", "name_lower", name="uq_tags_chat_name"),
    )


class TagMember(Base):
    __tablename__ = "tag_members"

    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger, default=None)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tag: Mapped[Tag] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class MentionCooldown(Base):
    """Коли тег востаннє викликали. У БД, а не в пам'яті — щоб рестарт не скидав паузу."""

    __tablename__ = "mention_cooldowns"

    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.chat_id", ondelete="CASCADE"), primary_key=True
    )
    #: Нормалізована назва тега або "all".
    tag_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_by: Mapped[Optional[int]] = mapped_column(BigInteger, default=None)
