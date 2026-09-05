import os
import sys
import json
import time
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from intelligence.creator_memory import CreatorMemoryStore

# =====================================================================
# CONFIGURAÇÃO DO BANCO DE DADOS LOCAL (COOLDOWN)
# =====================================================================
if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
    BASE_DIR = os.path.dirname(EXE_DIR) if os.path.basename(EXE_DIR) == 'dist' else EXE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASTA_CONFIG = os.path.join(BASE_DIR, "config")
ARQUIVO_HISTORICO = os.path.join(PASTA_CONFIG, "historico_otimizacao.json")
ARQUIVO_MEMORIA = os.path.join(PASTA_CONFIG, "creator_memory.sqlite3")


class PublicadorYouTube:
    def __init__(self, arquivo_token):
        self.arquivo_token = arquivo_token
        self.memory = CreatorMemoryStore(ARQUIVO_MEMORIA)

    def carregar_historico(self):
        if os.path.exists(ARQUIVO_HISTORICO):
            with open(ARQUIVO_HISTORICO, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def salvar_historico(self, video_id):
        """Compatibilidade com instalações antigas.

        O bloqueio real agora é feito pelo CreatorMemoryStore/SQLite. Este JSON
        continua sendo atualizado para não quebrar versões legadas do desktop.
        """
        historico = self.carregar_historico()
        historico[video_id] = datetime.now(timezone.utc).isoformat()
        with open(ARQUIVO_HISTORICO, 'w', encoding='utf-8') as f:
            json.dump(historico, f, indent=4)

    def obter_cliente_youtube(self):
        SCOPES = [
            'https://www.googleapis.com/auth/youtube.force-ssl',
            'https://www.googleapis.com/auth/yt-analytics.readonly'
        ]
        if os.path.exists(self.arquivo_token):
            creds = Credentials.from_authorized_user_file(self.arquivo_token, SCOPES)
            return build('youtube', 'v3', credentials=creds)
        raise Exception("Token do YouTube inválido ou desconectado.")

    def calcular_horario_pico(self):
        """Compatibilidade legada para agendamento genérico.

        O Command Center não trata estes horários fixos como Analytics real do
        canal; eles existem somente para o fluxo antigo de publicação agendada.
        """
        agora = datetime.now(timezone.utc)
        hora_atual_br = agora.astimezone(timezone(timedelta(hours=-3))).hour
        if hora_atual_br < 11:
            agendamento = agora.replace(hour=14, minute=30, second=0, microsecond=0)
        elif hora_atual_br < 18:
            agendamento = agora.replace(hour=21, minute=30, second=0, microsecond=0)
        else:
            amanha = agora + timedelta(days=1)
            agendamento = amanha.replace(hour=14, minute=30, second=0, microsecond=0)
        return agendamento.isoformat()

    def publicar_novo_conteudo(self, caminho_video, dados_seo, formato_conteudo, caminho_thumb=None, publicar_agora=True):
        """Realiza o upload de um novo arquivo de vídeo."""
        youtube = self.obter_cliente_youtube()

        titulo = dados_seo.get("titulos_virais", ["Vídeo Sem Título"])[0]
        descricao = dados_seo.get("descricao_seo", "")
        tags = dados_seo.get("tags", [])

        if "Short" in formato_conteudo:
            if "#shorts" not in titulo.lower():
                titulo += " #shorts"
            if "#shorts" not in descricao.lower():
                descricao += "\n\n#shorts"

        corpo_requisicao = {
            'snippet': {
                'title': titulo[:100],
                'description': descricao,
                'tags': tags,
                'categoryId': '27',
                'defaultLanguage': 'pt-BR'
            },
            'status': {
                'selfDeclaredMadeForKids': False
            }
        }

        if publicar_agora:
            corpo_requisicao['status']['privacyStatus'] = 'public'
        else:
            corpo_requisicao['status']['privacyStatus'] = 'private'
            corpo_requisicao['status']['publishAt'] = self.calcular_horario_pico()

        media_video = MediaFileUpload(caminho_video, chunksize=-1, resumable=True, mimetype='video/*')

        print(f"🚀 Iniciando upload inteligente de [{formato_conteudo}]...")
        requisicao_upload = youtube.videos().insert(
            part="snippet,status", body=corpo_requisicao, media_body=media_video
        )

        resposta = None
        while resposta is None:
            status, resposta = requisicao_upload.next_chunk()
            if status:
                print(f"📤 Enviando vídeo: {int(status.progress() * 100)}% concluído...")

        video_id = resposta.get('id')
        print(f"✅ Upload concluído! ID: {video_id}")
        self.salvar_historico(video_id)
        if video_id:
            self.memory.record_video_action(
                video_id=video_id,
                action_type="publish",
                surface="desktop_legacy_publisher",
                changed_fields=["title", "description", "tags"],
                before={},
                after=corpo_requisicao.get("snippet", {}),
                details={"format": formato_conteudo},
            )

        if caminho_thumb and os.path.exists(caminho_thumb) and "Short" not in formato_conteudo:
            try:
                print("🖼️ Aplicando miniatura profissional...")
                youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(caminho_thumb)).execute()
            except Exception as e:
                print(f"⚠️ Erro ao enviar miniatura: {str(e)}")

        return video_id

    def atualizar_video_existente(self, video_id, novo_titulo, novas_tags, nova_descricao=None):
        """Atualiza metadados e bloqueia reedições recentes feitas pela ferramenta."""
        self.memory.assert_not_recently_edited(video_id)
        youtube = self.obter_cliente_youtube()

        print(f"🛠️ Baixando dados atuais do vídeo ID: {video_id}...")
        video_response = youtube.videos().list(part="snippet,status", id=video_id).execute()

        if not video_response.get('items'):
            raise Exception("Vídeo não encontrado no canal.")

        video_data = video_response['items'][0]
        snippet = video_data['snippet']
        before = deepcopy(snippet)

        snippet['title'] = novo_titulo[:100]
        snippet['tags'] = novas_tags
        if nova_descricao:
            snippet['description'] = nova_descricao

        video_data['snippet'] = snippet

        print("🔥 Aplicando novo SEO no vídeo...")
        youtube.videos().update(
            part="snippet,status",
            body=video_data
        ).execute()

        changed_fields = [
            field for field in ("title", "description", "tags")
            if before.get(field) != snippet.get(field)
        ]
        self.memory.record_video_action(
            video_id=video_id,
            action_type="metadata_update",
            surface="desktop_audit",
            changed_fields=changed_fields,
            before=before,
            after=snippet,
            details={},
        )
        self.salvar_historico(video_id)
        print(f"✅ Vídeo {video_id} otimizado e protegido na memória persistente!")
        return True
