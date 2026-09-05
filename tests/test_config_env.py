from pathlib import Path

from src.config_env import atualizar_variavel_env


def test_adiciona_variavel_sem_apagar_conteudo(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "TIKTOK_CLIENT_KEY=abc\nTIKTOK_CLIENT_SECRET=xyz\n",
        encoding="utf-8",
    )

    atualizar_variavel_env(str(env), "GEMINI_API_KEYS", "g1,g2")

    conteudo = env.read_text(encoding="utf-8")
    assert "TIKTOK_CLIENT_KEY=abc" in conteudo
    assert "TIKTOK_CLIENT_SECRET=xyz" in conteudo
    assert "GEMINI_API_KEYS=g1,g2" in conteudo


def test_atualiza_variavel_existente_sem_duplicar(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "GEMINI_API_KEYS=antiga\nOUTRA_CONFIG=preservar\n",
        encoding="utf-8",
    )

    atualizar_variavel_env(str(env), "GEMINI_API_KEYS", "nova1,nova2")

    linhas = env.read_text(encoding="utf-8").splitlines()
    assert linhas.count("GEMINI_API_KEYS=nova1,nova2") == 1
    assert "GEMINI_API_KEYS=antiga" not in linhas
    assert "OUTRA_CONFIG=preservar" in linhas


def test_cria_diretorio_e_arquivo_quando_nao_existem(tmp_path: Path):
    env = tmp_path / "config" / ".env"

    atualizar_variavel_env(str(env), "GEMINI_API_KEYS", "chave")

    assert env.exists()
    assert env.read_text(encoding="utf-8") == "GEMINI_API_KEYS=chave\n"
