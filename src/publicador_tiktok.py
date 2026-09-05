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
Caminho_ENV = os.path.join(DIRETORIO_RAIZ, "config", ".env")

load_dotenv(Caminho_ENV)

CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")

# 🏠 O TIKTOK EXIGE LOCALHOST EXATAMENTE ASSIM:
URI_REDIRECIONAMENTO = "http://localhost:8080/callback/"
PORTA_REDIRECIONAMENTO = 8080
ARQUIVO_TOKEN = os.path.join(DIRETORIO_RAIZ, "config", "tiktok_token.json")

class TikTokCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/favicon'):
            self.send_response(204); self.end_headers(); return

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        query = urlparse(self.path).query
        parametros = parse_qs(query)
        
        if "code" in parametros:
            self.server.auth_code = parametros["code"][0]
            html_sucesso = "<html><body style='font-family: Arial; text-align: center; margin-top: 50px; background: #0f172a; color: #10b981;'><h1>✅ Autenticação Local Concluída!</h1><p style='color: white;'>O arquivo de token foi gerado. Pode fechar esta janela e voltar ao Meta Director Pro.</p></body></html>"
            self.wfile.write(html_sucesso.encode('utf-8'))
        else:
            self.wfile.write(b"Erro: Codigo nao encontrado na url.")
            
    def log_message(self, format, *args): pass

class ReusableServer(HTTPServer):
    allow_reuse_address = True

class PublicadorTikTok:
    def __init__(self):
        if not CLIENT_KEY: raise ValueError("🚨 ERRO: TIKTOK_CLIENT_KEY não encontrado no .env!")
        if not CLIENT_SECRET: raise ValueError("🚨 ERRO: TIKTOK_CLIENT_SECRET não encontrado no .env!")
        self.client_key = CLIENT_KEY
        self.client_secret = CLIENT_SECRET
        self.token_url = "https://open.tiktokapis.com/v2/oauth/token/"
        self.code_verifier = ""

    def _obter_access_token_salvo(self):
        if not os.path.exists(ARQUIVO_TOKEN): return None
        with open(ARQUIVO_TOKEN, "r") as f:
            try:
                resposta = json.load(f)
                if "error" in resposta: return None
                if "data" in resposta and "access_token" in resposta["data"]: return resposta["data"]["access_token"]
                return resposta.get("access_token")
            except:
                return None

    def _gerar_pkce(self):
        self.code_verifier = secrets.token_urlsafe(64)
        sha256_hash = hashlib.sha256(self.code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(sha256_hash).decode('utf-8').rstrip('=')
        return code_challenge

    def autenticar(self):
        if self._obter_access_token_salvo(): return True
        if os.path.exists(ARQUIVO_TOKEN): os.remove(ARQUIVO_TOKEN)

        code_challenge = self._gerar_pkce()

        url_auth = (
            "https://www.tiktok.com/v2/auth/authorize/?"
            + urlencode({
                "client_key": self.client_key,
                "response_type": "code",
                "scope": "video.upload,video.publish",
                "redirect_uri": URI_REDIRECIONAMENTO,
                "state": "meta_director_pro",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256"
            })
        )
        
        webbrowser.open(url_auth)
        server = ReusableServer(('localhost', PORTA_REDIRECIONAMENTO), TikTokCallbackHandler)
        server.auth_code = None
        while not server.auth_code: server.handle_request()
            
        codigo_autorizacao = server.auth_code
        server.server_close()
        
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
            "code_verifier": self.code_verifier
        }
        
        resposta = requests.post(self.token_url, headers=headers, data=data)
        json_resp = resposta.json()
        
        if "error" in json_resp or resposta.status_code != 200:
            raise Exception(f"Erro do Servidor TikTok: {json_resp.get('error_description', json_resp)}")
            
        os.makedirs(os.path.dirname(ARQUIVO_TOKEN), exist_ok=True)
        with open(ARQUIVO_TOKEN, "w") as f: 
            json.dump(json_resp, f)
        print("✅ Sucesso Absoluto! O arquivo tiktok_token.json foi gerado via localhost.")
            
    def publicar_video(self, caminho_video, titulo):
        token = self._obter_access_token_salvo()
        if not token: raise Exception("TikTok não conectado. Faça a conexão na aba Painel de Controle.")

        tamanho_video = os.path.getsize(caminho_video)
        headers_init = { "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8" }
        dados_init = {
            "post_info": { "title": titulo, "privacy_level": "PUBLIC_TO_EVERYONE", "disable_duet": False, "disable_comment": False, "disable_stitch": False, "video_cover_timestamp_ms": 1000 },
            "source_info": { "source": "FILE_UPLOAD", "video_size": tamanho_video, "chunk_size": tamanho_video, "total_chunk_count": 1 }
        }
        
        resposta_init = requests.post("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/", headers=headers_init, json=dados_init)
        if resposta_init.status_code != 200: raise Exception(f"Erro na inicialização do TikTok: {resposta_init.text}")
        json_init = resposta_init.json()
        
        if "data" not in json_init or "publish_id" not in json_init["data"]: raise Exception(f"Resposta inesperada do TikTok: {json_init}")
            
        publish_id = json_init["data"]["publish_id"]
        upload_url = json_init["data"]["upload_url"]

        headers_upload = { "Content-Range": f"bytes 0-{tamanho_video-1}/{tamanho_video}", "Content-Type": "video/mp4" }
        with open(caminho_video, "rb") as arquivo_video:
            resposta_upload = requests.put(upload_url, headers=headers_upload, data=arquivo_video)

        if resposta_upload.status_code not in (200, 201, 206): raise Exception(f"Erro ao transferir o arquivo: {resposta_upload.text}")
        return publish_id