from __future__ import annotations

from bot.services.mention import MentionTarget, build_mention_messages, render_mention


def targets(count: int):
    return [MentionTarget(user_id=index, name=f"Юзер{index}") for index in range(1, count + 1)]


def test_render_mention_uses_user_id_link():
    assert render_mention(MentionTarget(7, "Влад")) == '<a href="tg://user?id=7">Влад</a>'


def test_render_mention_escapes_html():
    rendered = render_mention(MentionTarget(1, "<b>злий</b> & Ко"))
    assert "&lt;b&gt;" in rendered
    assert "&amp;" in rendered
    assert "<b>" not in rendered


def test_empty_targets_produce_no_messages():
    assert build_mention_messages([], header="🔔 @all") == []


def test_batches_are_split_by_size():
    messages = build_mention_messages(targets(13), header="🔔 @all", batch_size=6)
    assert len(messages) == 3
    assert messages[0].count("tg://user") == 6
    assert messages[1].count("tg://user") == 6
    assert messages[2].count("tg://user") == 1


def test_header_only_on_first_message():
    messages = build_mention_messages(targets(8), header="🔔 @all", batch_size=4)
    assert messages[0].startswith("🔔 @all\n")
    assert "🔔" not in messages[1]


def test_every_target_is_mentioned_exactly_once():
    people = targets(25)
    joined = " ".join(build_mention_messages(people, batch_size=6))
    for target in people:
        assert joined.count(f'tg://user?id={target.user_id}"') == 1
