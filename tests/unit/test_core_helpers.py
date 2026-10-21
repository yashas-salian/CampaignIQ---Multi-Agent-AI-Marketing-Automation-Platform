import json

import pytest

from src.finetune.prompt import build_messages, parse_label
from src.llm_json import generate_json, parse_llm_json
from src.providers.crypto import decrypt_key, encrypt_key, mask_key


class TestParseLlmJson:
    def test_strips_markdown_fences(self):
        assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_repairs_escaped_apostrophes(self):
        assert parse_llm_json('{"copy": "the campaign\\\'s hook"}') == {"copy": "the campaign's hook"}

    def test_tolerates_raw_newlines_inside_strings(self):
        assert parse_llm_json('{"copy": "line one\nline two"}')["copy"] == "line one\nline two"


class TestGenerateJson:
    def test_resamples_after_a_truncated_reply(self, fake_llm):
        llm = fake_llm('{"a": "trunc', '{"a": "ok"}')
        assert generate_json(llm, "p", system="s") == {"a": "ok"}
        assert len(llm.prompts) == 2

    def test_gives_up_after_max_attempts(self, fake_llm):
        llm = fake_llm("not json")
        with pytest.raises(json.JSONDecodeError):
            generate_json(llm, "p", system="s")
        assert len(llm.prompts) == 3


class TestCrypto:
    def test_round_trip(self):
        token = encrypt_key("sk-live-1234567890")
        assert token != "sk-live-1234567890"
        assert decrypt_key(token) == "sk-live-1234567890"

    def test_random_nonce_per_encryption(self):
        assert encrypt_key("same") != encrypt_key("same")

    def test_mask_shows_only_last_four(self):
        assert mask_key("sk-abcdef1234") == "****1234"
        assert mask_key("abc") == "****"


class TestClassifierPrompt:
    def test_exact_label(self):
        assert parse_label("food_beverage") == "food_beverage"

    def test_label_with_noise(self):
        assert parse_label(' "Healthcare". ') == "healthcare"
        assert parse_label("Category: b2b_saas") == "b2b_saas"

    def test_invalid_reply_is_none(self):
        assert parse_label("groceries") is None

    def test_messages_list_every_category(self):
        user = build_messages("  An idea  ")[1]["content"]
        assert "Idea: An idea\n" in user and "travel_hospitality" in user and "other" in user
