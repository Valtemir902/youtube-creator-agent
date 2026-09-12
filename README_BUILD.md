# Build do YouTube Creator Agent Elite

## Objetivo

O mesmo backend/VPS atende Windows, Android, web/mobile e ChatGPT MCP. Nenhum segredo permanente deve ser embutido no EXE ou APK.

## Desktop Windows

Modo de desenvolvimento:

```powershell
python main.py
```

Build local:

```powershell
python scripts/build_windows.py
```

Saída esperada:

```text
dist/YouTube-Creator-Agent-Elite.exe
dist/YouTube-Creator-Agent-Elite.exe.sha256
```

Requisitos: Python compatível com o projeto e dependências do repositório. O script executa compileall e pytest antes do empacotamento.

## Android

Arquitetura: Capacitor com assets locais, cache/snapshot local e motor determinístico leve. Dados oficiais, autenticação, OAuth e ações críticas continuam na VPS. Não há IA local no Android.

Requisitos:

- Node.js e npm
- JDK compatível com Android Gradle Plugin
- Android Studio/Android SDK
- `ANDROID_HOME` ou `ANDROID_SDK_ROOT`

Primeira inicialização do projeto Android:

```powershell
cd mobile
npm install
npx cap add android
cd ..
```

Build:

```powershell
python scripts/build_android.py
```

Saída esperada:

```text
dist/YouTube-Creator-Agent-Elite.apk
dist/YouTube-Creator-Agent-Elite.apk.sha256
```

O build inicial é para teste interno. Publicação em loja, assinatura release e versionamento de distribuição são etapas separadas.

## Motor móvel

`mobile/src/native-engine.ts` contém somente cálculos determinísticos leves. O contrato de entrada é versionado em `native_intelligence/contracts/channel_snapshot_v1.schema.json`.

Regra: fatos oficiais vêm da VPS/YouTube; o motor local calcula scores e diagnósticos derivados sem usar Gemini/OpenAI/Groq/xAI. IA externa só deve ser chamada por ação explícita do usuário.

## Segurança

- VPS é a autoridade de autenticação, OAuth, permissões, auditoria e escrita no YouTube.
- Tokens locais devem usar armazenamento seguro da plataforma em produção.
- Nenhuma API key privada ou secret da VPS deve ser empacotada.
- Toda escrita continua em fluxo preview -> confirmação -> apply -> readback/rollback quando aplicável.

## Sincronização da máquina de desenvolvimento

Depois do merge no branch de desenvolvimento, a estação local pode apenas atualizar:

```powershell
git fetch origin
git switch feat/web-dashboard-v1
git pull --ff-only origin feat/web-dashboard-v1
```

Antes disso, verifique `git status` e preserve `.env`, credenciais e arquivos locais não versionados.
