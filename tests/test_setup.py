import stat

import pytest

from emporio import setup


def test_owner_login_is_hashed_and_private():
    setup.create_owner("Marlon", "violao-de-7-cordas")
    raw = setup.OWNER_FILE.read_text()
    assert "violao-de-7-cordas" not in raw
    assert stat.S_IMODE(setup.OWNER_FILE.stat().st_mode) == 0o600
    assert setup.check_login("Marlon", "violao-de-7-cordas")
    assert not setup.check_login("Marlon", "senha-errada")
    assert not setup.check_login("Márlon", "violao-de-7-cordas")  # não quebra com acento


def test_short_password_is_rejected():
    with pytest.raises(ValueError):
        setup.create_owner("dono", "123")


def test_settings_keep_other_keys_and_are_private():
    setup.save_settings("anthropic", "claude-opus-5-5", "sk-ant-teste-123456", "livre")
    setup.save_settings("ollama", "qwen2.5:1.5b", None, "restrito")
    saved = setup.load_settings()
    assert saved["LLM_PROVIDER"] == "ollama" and saved["EMPORIO_MODE"] == "restrito"
    assert saved["ANTHROPIC_API_KEY"] == "sk-ant-teste-123456"  # trocar de IA não apaga a chave
    assert stat.S_IMODE(setup.SETTINGS_FILE.stat().st_mode) == 0o600
    assert setup.mask("sk-ant-teste-123456") == "sk-a…3456"
