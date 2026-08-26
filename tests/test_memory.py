from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.clara.memory import BoundedConversationMemory


def save_isolated_turn(memory: BoundedConversationMemory, index: int) -> None:
    memory.save_turn(
        f"key-{index}",
        f"client-{index}",
        f"question-{index}",
        f"answer-{index}",
        {},
        "invoice",
    )


class BoundedConversationMemoryTests(unittest.TestCase):
    def test_evicts_oldest_session(self) -> None:
        memory = BoundedConversationMemory(max_sessions=2)
        memory.save_turn("one", "A", "um", "resposta", {}, "tax_question")
        memory.save_turn("two", "A", "dois", "resposta", {}, "tax_question")
        memory.save_turn("three", "A", "três", "resposta", {}, "tax_question")
        self.assertEqual(memory.snapshot("one"), {})
        self.assertEqual(len(memory), 2)

    def test_returns_copy_instead_of_mutable_record(self) -> None:
        memory = BoundedConversationMemory(max_sessions=2)
        memory.save_turn("one", "A", "um", "resposta", {"UF": "SP"}, "tax_question")
        loaded = memory.load("one", "A")
        loaded["facts"]["UF"] = "RJ"
        self.assertEqual(memory.snapshot("one")["facts"]["UF"], "SP")

    def test_expires_content_after_session_ttl(self) -> None:
        instant = [0.0]
        memory = BoundedConversationMemory(10, ttl_seconds=60, clock=lambda: instant[0])
        memory.save_turn("key", "client", "segredo sintético", "resposta", {}, "invoice")
        instant[0] = 61.0
        self.assertEqual(memory.snapshot("key"), {})

    def test_concurrent_sessions_never_mix_content(self) -> None:
        memory = BoundedConversationMemory(200)
        with ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(lambda index: save_isolated_turn(memory, index), range(100)))
        for index in range(100):
            turns = memory.snapshot(f"key-{index}")["turns"]
            self.assertEqual(
                [turn["content"] for turn in turns],
                [f"question-{index}", f"answer-{index}"],
            )


if __name__ == "__main__":
    unittest.main()
