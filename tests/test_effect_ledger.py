"""C9：副作用账本测试——外部效果幂等去重（邮件不重复发送）"""

from __future__ import annotations

from packages.application.commands.effect_ledger import has_effect, register_effect
from packages.domain.enums import EffectKind
from packages.storage.db import session_scope


def test_register_effect_idempotent(isolated_db):
    with session_scope() as session:
        key = "mail:2026-09-03:me@example.com:send"

        record, created1 = register_effect(
            session, effect_key=key, kind=EffectKind.mail_send, payload={"to": "me"}
        )
        assert created1 is True
        assert record is not None

        record2, created2 = register_effect(
            session, effect_key=key, kind=EffectKind.mail_send, payload={"to": "me"}
        )
        assert created2 is False
        assert record2.id == record.id  # 返回既有记录


def test_has_effect(isolated_db):
    with session_scope() as session:
        assert has_effect(session, "nope") is False
        register_effect(session, effect_key="yes", kind=EffectKind.provider_call)
        assert has_effect(session, "yes") is True


def test_email_effect_dedup_integration(isolated_db):
    """send_brief_email handler 语义：先查账本，未登记才发（幂等去重）"""
    sent: list[str] = []

    def send_email(recipient: str) -> bool:
        # 模拟 notifier：副作用不可撤回
        sent.append(recipient)
        return True

    with session_scope() as session:
        for _ in range(3):  # 模拟 3 次重试/重复调度
            key = "mail:2026-09-03:me@example.com:send"
            if has_effect(session, key):
                continue
            register_effect(session, effect_key=key, kind=EffectKind.mail_send)
            send_email("me@example.com")

    assert sent == ["me@example.com"]  # 只发一次
