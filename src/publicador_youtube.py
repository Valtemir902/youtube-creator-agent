import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

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

class PublicadorYouTube:
    def __init__(self, arquivo_token):
        self.arquivo_token = arquivo_token

    def carregar_historico(self):
        if os.path.exists(ARQUIVO_HISTORICO):
            with open(ARQUIVO_HISTORICO, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def salvar_historico(self, video_id):
        historico = self.carregar_historico()
        historico[video_id] = datetime.now(timezone.utc).isoformat()
        with open(ARQUIVO_HISTORICO, 'w', encoding='utf-8') as f:
            json.dump(historico, f, indent=4)

    def obter_cliente_youtube(self):
        # Escopos atualizados para bater com o Analista e não dar erro de token
        SCOPES = [
            'https://www.googleapis.com/auth/youtube.force-ssl',
            'https://www.googleapis.com/auth/yt-analytics.readonly'
        ]
        if os.path.exists(self.arquivo_token):
            creds = Credentials.from_authorized_user_file(self.arquivo_token, SCOPES)
            return build('youtube', 'v3', credentials=creds)
        raise Exception("Token do YouTube inválido ou desconectado.")

    def calcular_horario_pico(self):
        """Calcula o próximo horário de pico no Brasil para agendar o vídeo"""
        agora = datetime.now(timezone.utc)
        hora_atual_br = agora.astimezone(timezone(timedelta(hours=-3))).hour
        
        # Define os horários de pico gerais (11h30 da manhã e 18h30 da tarde)
        if hora_atual_br < 11:
            # Agenda para hoje às 11:30 BRT
            agendamento = agora.replace(hour=14, minute=30, second=0, microsecond=0) # 14h UTC = 11h BRT
        elif hora_atual_br < 18:
            # Agenda para hoje às 18:30 BRT
            agendamento = agora.replace(hour=21, minute=30, second=0, microsecond=0) # 21h UTC = 18h BRT
        else:
            # Agenda para amanhã às 11:30 BRT
            amanha = agora + timedelta(days=1)
            agendamento = amanha.replace(hour=14, minute=30, second=0, microsecond=0)
            
        return agendamento.isoformat()

    def publicar_novo_conteudo(self, caminho_video, dados_seo, formato_conteudo, caminho_thumb=None, publicar_agora=True):
        """Realiza o Upload Inteligente de um novo arquivo de vídeo"""
        youtube = self.obter_cliente_youtube()

        titulo = dados_seo.get("titulos_virais", ["Vídeo Sem Título"])[0]
        descricao = dados_seo.get("descricao_seo", "")
        tags = dados_seo.get("tags", [])
        
        if "Short" in formato_conteudo:
            if "#shorts" not in titulo.lower(): titulo += " #shorts"
            if "#shorts" not in descricao.lower(): descricao += "\n\n#shorts"

        corpo_requisicao = {
            'snippet': {
                'title': titulo[:100], 
                'description': descricao,
                'tags': tags,
                'categoryId': '27', # Categoria Educação (Ideal para Agro/Tech/Tutoriais)
                'defaultLanguage': 'pt-BR'
            },
            'status': {
                'selfDeclaredMadeForKids': False
            }
        }

        # Lógica de Horário de Pico vs Publicação Imediata
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
        self.salvar_historico(video_id) # Blinda contra atualizações acidentais recentes

        if caminho_thumb and os.path.exists(caminho_thumb) and "Short" not in formato_conteudo:
            try:
                print("🖼️ Aplicando miniatura profissional...")
                youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(caminho_thumb)).execute()
            except Exception as e:
                print(f"⚠️ Erro ao enviar miniatura: {str(e)}")

        return video_id

    def atualizar_video_existente(self, video_id, novo_titulo, novas_tags, nova_descricao=None):
        """Cirurgia de SEO: Atualiza metadados de vídeos já publicados (Usado pelo Auditor)"""
        youtube = self.obter_cliente_youtube()
        
        print(f"🛠️ Baixando dados atuais do vídeo ID: {video_id}...")
        video_response = youtube.videos().list(part="snippet,status", id=video_id).execute()
        
        if not video_response.get('items'):
            raise Exception("Vídeo não encontrado no canal.")
            
        video_data = video_response['items'][0]
        snippet = video_data['snippet']
        
        # Aplicamos a cirurgia apenas no que for necessário
        snippet['title'] = novo_titulo[:100]
        snippet['tags'] = novas_tags
        
        if nova_descricao:
            snippet['description'] = nova_descricao
            
        # O YouTube exige que a categoria seja mantida no update
        video_data['snippet'] = snippet
        
        print(f"🔥 Aplicando novo SEO viral no vídeo...")
        youtube.videos().update(
            part="snippet,status",
            body=video_data
        ).execute()
        
        self.salvar_historico(video_id) # Registra no banco para o Cooldown Anti-Ban de 15 dias
        print(f"✅ Vídeo {video_id} otimizado e protegido com sucesso!")
        return True