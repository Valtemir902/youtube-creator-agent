from __future__ import annotations

import os
from pathlib import Path


def atualizar_variavel_env(caminho_env: str, chave: str, valor: str) -> None:
    """Atualiza uma variável no .env sem apagar as demais configurações.

    Mantém comentários, linhas vazias e outras credenciais já existentes.
    Se a chave ainda não existir, ela é adicionada ao final do arquivo.
    """
    if not chave or "=" in chave or "\n" in chave or "\r" in chave:
        raise ValueError("Nome de variável de ambiente inválido.")

    path = Path(caminho_env)
    path.parent.mkdir(parents=True, exist_ok=True)

    linhas = []
    if path.exists():
        linhas = path.read_text(encoding="utf-8").splitlines()

    prefixo = f"{chave}="
    nova_linha = f"{chave}={valor}"
    encontrado = False
    resultado = []

    for linha in linhas:
        if linha.startswith(prefixo):
            if not encontrado:
                resultado.append(nova_linha)
                encontrado = True
            continue
        resultado.append(linha)

    if not encontrado:
        resultado.append(nova_linha)

    conteudo = "\n".join(resultado).rstrip("\n") + "\n"
    temporario = path.with_suffix(path.suffix + ".tmp")
    temporario.write_text(conteudo, encoding="utf-8")
    os.replace(temporario, path)
