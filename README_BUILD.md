# Builds locais do YouTube Creator Agent Elite

## Windows

O build Windows oficial agora e isolado e reproduzivel. Ele cria um ambiente virtual limpo somente para empacotamento, fixa PySide6/shiboken6 na mesma versao e so publica o EXE em `artifacts/windows/` se o binario gerado passar um smoke test real do runtime Qt.

Execute no Windows:

```powershell
python scripts/build_windows.py
```

Artefatos finais:

- `artifacts/windows/YouTube-Creator-Agent-Elite.exe`
- `artifacts/windows/YouTube-Creator-Agent-Elite.exe.sha256`
- `artifacts/windows/build-report.json`

Nao use executaveis antigos deixados em `build/dist-*`, `dist/` ou pastas temporarias. Esses caminhos sao somente residuos/intermediarios de desenvolvimento.

O smoke test executa o proprio EXE com `--self-test`, carrega PySide6, shiboken6, QtCore, QtWidgets e o modulo desktop real. Se houver o erro historico `DLL load failed while importing QtWidgets` ou incompatibilidade entre DLLs Qt, o script falha e nao copia o binario para `artifacts/windows/`.

## Android

Execute:

```powershell
python scripts/build_android.py
```

O Android nao empacota IA local. O app usa motor deterministico leve no dispositivo e continua usando a VPS para autenticacao, OAuth, dados oficiais e autorizacao.

## Seguranca

Nenhum segredo de producao deve ser empacotado no EXE ou APK. A VPS continua sendo a autoridade de autenticacao, OAuth, permissoes e acoes criticas. Assinatura Authenticode e assinatura comercial Android devem ser configuradas separadamente para distribuicao publica.
