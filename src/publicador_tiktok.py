import os
import json
import webbrowser
import requests
import secrets
import base64
import hashlib
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIRETORIO_RAIZ = os.path.dirname(DIRETORIO_ATUAL)
CAMINHO_ENV = os.path.join(DIRETORIO_RAIZ, "config", ".env")

load_dotenv(CAMINHO_ENV)

CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")

URI_REDIRECIONAMENTO = "http://localhost:8080/callback/"
PORTA_REDIRECIONAMENTO = 8080
ARQUIVO_TOKEN = os.path.join(DIRETORIO_RAIZ, "config", "tiktok_token.json")

API_BASE = "https://open.tiktokapis.com/v2"
TIMEOUT_HTTP = 30


class TikTokCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/favicon"):
            self.send_response(204)
            self.end_headers()
            return

        query = urlparse(self.path).query
        parametros = parse_qs(query)

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        if "code" in parametros:
            self.server.auth_code = parametros["code"][0]
            html_sucesso = (
                "<html><body style='font-family: Arial; text-align: center; margin-top: 50px; "
                "background: #0f172a; color: #10b981;'><h1>Autenticação concluída</h1>"
                "<p style='color: white;'>Pode fechar esta janela e voltar ao aplicativo.</p>"
                "</body></html>"
            )
            self.wfile.write(html_sucesso.encode("utf-8"))
            return

        erro = parametros.get("error_description", parametros.get("error", ["Código não encontrado."]))[0]
        self.server.auth_error = erro
        self.wfile.write(f"Erro de autenticação: {erro}".encode("utf-8"))

    def log_message(self, format, *args):
        pass


class ReusableServer(HTTPServer):
    allow_reuse_address = True


class PublicadorTikTok:
    def __init__(self):
        if not CLIENT_KEY:
            raise ValueError("TIKTOK_CLIENT_KEY não encontrado no .env.")
        if not CLIENT_SECRET:
            raise ValueError("TIKTOK_CLIENT_SECRET não encontrado no .env.")

        self.client_key = CLIENT_KEY
        self.client_secret = CLIENT_SECRET
        self.token_url = f"{API_BASE}/oauth/token/"
        self.code_verifier = ""

    def _obter_access_token_salvo(self):
        if not os.path.exists(ARQUIVO_TOKEN):
            return None

        try:
            with open(ARQUIVO_TOKEN, "r", encoding="utf-8") as arquivo:
                resposta = json.load(arquivo)
        except (OSError, json.JSONDecodeError):
            return None

        if "error" in resposta:
            return None
        if "data" in resposta and "access_token" in resposta["data"]:
            return resposta["data"]["access_token"]
        return resposta.get("access_token")

    def _gerar_pkce(self):
        self.code_verifier = secrets.token_urlsafe(64)
        sha256_hash = hashlib.sha256(self.code_verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(sha256_hash).decode("utf-8").rstrip("=")

    @staticmethod
    def _validar_resposta_api(resposta, contexto):
        try:
            payload = resposta.json()
        except ValueError as exc:
            raise RuntimeError(
                f"{contexto}: resposta inválida do TikTok (HTTP {resposta.status_code})."
            ) from exc

        erro = payload.get("error") or {}
        codigo = erro.get("code")
        if resposta.status_code >= 400 or (codigo and codigo != "ok"):
            mensagem = erro.get("message") or payload.get("error_description") or resposta.text
            raise RuntimeError(f"{contexto}: {codigo or resposta.status_code} - {mensagem}")

        return payload

    def autenticar(self):
        if self._obter_access_token_salvo():
            return True

        if os.path.exists(ARQUIVO_TOKEN):
            os.remove(ARQUIVO_TOKEN)

        code_challenge = self._gerar_pkce()
        state = secrets.token_urlsafe(24)

        url_auth = (
            "https://www.tiktok.com/v2/auth/authorize/?"
            + urlencode(
                {
                    "client_key": self.client_key,
                    "response_type": "code",
                    "scope": "video.upload,video.publish",
                    "redirect_uri": URI_REDIRECIONAMENTO,
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

        webbrowser.open(url_auth)
        server = ReusableServer(("localhost", PORTA_REDIRECIONAMENTO), TikTokCallbackHandler)
        server.auth_code = None
        server.auth_error = None
        server.timeout = 180

        while not server.auth_code and not server.auth_error:
            server.handle_request()
            if server.auth_code is None and server.auth_error is None:
                server.server_close()
                raise TimeoutError("Tempo limite excedido aguardando autenticação do TikTok.")

        codigo_autorizacao = server.auth_code
        erro_autenticacao = server.auth_error
        server.server_close()

        if erro_autenticacao:
            raise RuntimeError(f"Autenticação TikTok cancelada ou recusada: {erro_autenticacao}")

        self._obter_token(codigo_autorizacao)
        return True

    def _obter_token(self, code):
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": URI_REDIRECIONAMENTO,
            "code_verifier": self.code_verifier,
        }

        resposta = requests.post(
            self.token_url,
            headers=headers,
            data=data,
            timeout=TIMEOUT_HTTP,
        )
        payload = self._validar_resposta_api(resposta, "Falha ao obter token do TikTok")

        os.makedirs(os.path.dirname(ARQUIVO_TOKEN), exist_ok=True)
        with open(ARQUIVO_TOKEN, "w", encoding="utf-8") as arquivo:
            json.dump(payload, arquivo, ensure_ascii=False, indent=2)

    def obter_creator_info(self):
        token = self._obter_access_token_salvo()
        if not token:
            raise RuntimeError("TikTok não conectado. Faça a conexão no Painel de Controle.")

        resposta = requests.post(
            f"{API_BASE}/post/publish/creator_info/query/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={},
            timeout=TIMEOUT_HTTP,
        )
        payload = self._validar_resposta_api(resposta, "Falha ao consultar informações do criador")
        return payload.get("data", {})

    def publicar_video(
        self,
        caminho_video,
        titulo,
        privacy_level="SELF_ONLY",
        disable_duet=False,
        disable_comment=False,
        disable_stitch=False,
        is_aigc=False,
    ):
        token = self._obter_access_token_salvo()
        if not token:
            raise RuntimeError("TikTok não conectado. Faça a conexão no Painel de Controle.")
        if not os.path.isfile(caminho_video):
            raise FileNotFoundError(f"Vídeo não encontrado: {caminho_video}")

        creator_info = self.obter_creator_info()
        opcoes_privacidade = creator_info.get("privacy_level_options") or []
        if opcoes_privacidade and privacy_level not in opcoes_privacidade:
            raise ValueError(
                f"Privacidade '{privacy_level}' não permitida para esta conta. "
                f"Opções disponíveis: {', '.join(opcoes_privacidade)}"
            )

        tamanho_video = os.path.getsize(caminho_video)
        if tamanho_video <= 0:
            raise ValueError("O arquivo de vídeo está vazio.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        dados_init = {
            "post_info": {
                "title": titulo,
                "privacy_level": privacy_level,
                "disable_duet": bool(disable_duet),
                "disable_comment": bool(disable_comment),
                "disable_stitch": bool(disable_stitch),
                "video_cover_timestamp_ms": 1000,
                "is_aigc": bool(is_aigc),
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": tamanho_video,
                "chunk_size": tamanho_video,
                "total_chunk_count": 1,
            },
        }

        resposta_init = requests.post(
            f"{API_BASE}/post/publish/video/init/",
            headers=headers,
            json=dados_init,
            timeout=TIMEOUT_HTTP,
        )
        payload_init = self._validar_resposta_api(
            resposta_init, "Falha ao inicializar publicação direta no TikTok"
        )

        dados = payload_init.get("data") or {}
        publish_id = dados.get("publish_id")
        upload_url = dados.get("upload_url")
        if not publish_id or not upload_url:
            raise RuntimeError(f"Resposta inesperada do TikTok: {payload_init}")

        headers_upload = {
            "Content-Range": f"bytes 0-{tamanho_video - 1}/{tamanho_video}",
            "Content-Type": "video/mp4",
        }
        with open(caminho_video, "rb") as arquivo_video:
            resposta_upload = requests.put(
                upload_url,
                headers=headers_upload,
                data=arquivo_video,
                timeout=300,
            )

        if resposta_upload.status_code not in (200, 201, 206):
            raise RuntimeError(
                f"Falha ao transferir vídeo para o TikTok: HTTP {resposta_upload.status_code} - "
                f"{resposta_upload.text}"
            )

        return publish_id

    def consultar_status_publicacao(self, publish_id):
        token = self._obter_access_token_salvo()
        if not token:
            raise RuntimeError("TikTok não conectado.")

        resposta = requests.post(
            f"{API_BASE}/post/publish/status/fetch/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
            timeout=TIMEOUT_HTTP,
        )
        payload = self._validar_resposta_api(resposta, "Falha ao consultar publicação TikTok")
        return payload.get("data", {})
