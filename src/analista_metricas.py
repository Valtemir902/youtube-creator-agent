import os
import sys
import json
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# =====================================================================
# CONFIGURAÇÃO DE AMBIENTE E BANCO DE DADOS LOCAL
# =====================================================================
if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
    BASE_DIR = os.path.dirname(EXE_DIR) if os.path.basename(EXE_DIR) == 'dist' else EXE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASTA_CONFIG = os.path.join(BASE_DIR, "config")
ARQUIVO_HISTORICO = os.path.join(PASTA_CONFIG, "historico_otimizacao.json")
ARQUIVO_SECRET = os.path.join(PASTA_CONFIG, "client_secret.json")

DIAS_DE_COOLDOWN = 15

class AnalistaCanal:
    def __init__(self, arquivo_token, api_keys):
        self.arquivo_token = arquivo_token
        self.api_keys = api_keys
        self.indice_chave = 0

    def carregar_historico(self):
        if os.path.exists(ARQUIVO_HISTORICO):
            with open(ARQUIVO_HISTORICO, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def rotacionar_gemini(self, prompt):
        max_tentativas = len(self.api_keys)
        ultimo_erro = ""
        for i in range(max_tentativas):
            chave = self.api_keys[self.indice_chave]
            try:
                genai.configure(api_key=chave)
                model = genai.GenerativeModel(
                    'gemini-2.5-flash',
                    generation_config={"response_mime_type": "application/json"}
                )
                return model.generate_content(prompt).text
            except Exception as e:
                ultimo_erro = str(e)
                self.indice_chave = (self.indice_chave + 1) % max_tentativas
        raise Exception(f"Todas as chaves do Gemini falharam. Erro: {ultimo_erro}")

    def obter_clientes_youtube(self):
        SCOPES = [
            'https://www.googleapis.com/auth/youtube.force-ssl',
            'https://www.googleapis.com/auth/yt-analytics.readonly'
        ]
        creds = None
        if os.path.exists(self.arquivo_token):
            creds = Credentials.from_authorized_user_file(self.arquivo_token, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try: creds.refresh(Request())
                except: creds = None
            if not creds:
                flow = InstalledAppFlow.from_client_secrets_file(ARQUIVO_SECRET, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.arquivo_token, 'w') as token_file:
                token_file.write(creds.to_json())

        return build('youtube', 'v3', credentials=creds), build('youtubeAnalytics', 'v2', credentials=creds)

    def buscar_tendencias_youtube_publicas(self, termo_nicho, sinal_progresso=None):
        """Varre a YouTube Data API v3 para extrair vídeos e termos em alta recentes"""
        if sinal_progresso:
            sinal_progresso.emit(f"🌐 Conectando à YouTube Data API v3 para varrer concorrentes em alta ({termo_nicho})...")
        
        youtube_data, _ = self.obter_clientes_youtube()
        data_limite = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        
        try:
            resposta = youtube_data.search().list(
                q=termo_nicho,
                part="snippet",
                type="video",
                order="viewCount",
                publishedAfter=data_limite,
                maxResults=10,
                regionCode="BR",
                relevanceLanguage="pt"
            ).execute()
            
            titulos_analisados = []
            for item in resposta.get("items", []):
                snippet = item.get("snippet", {})
                titulos_analisados.append({
                    "titulo": snippet.get("title"),
                    "canal": snippet.get("channelTitle")
                })
            return titulos_analisados
        except:
            return [{"titulo": termo_nicho, "canal": "Mercado Geral"}]

    def calcular_idade_video(self, data_publicacao_str):
        data_pub = datetime.strptime(data_publicacao_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        agora = datetime.now(timezone.utc)
        diferenca = agora - data_pub
        if diferenca.days == 0: return f"{diferenca.seconds // 3600} horas atrás", diferenca.days
        elif diferenca.days < 30: return f"{diferenca.days} dias atrás", diferenca.days
        else: return f"{diferenca.days // 30} meses atrás", diferenca.days

    def auditar_canal_profundo(self, sinal_progresso=None):
        if sinal_progresso: sinal_progresso.emit("🔄 Conectando às APIs do YouTube Studio e Analytics[cite: 1]...")
        
        youtube_data, youtube_analytics = self.obter_clientes_youtube()
        historico_otimizacoes = self.carregar_historico()
        
        if sinal_progresso: sinal_progresso.emit("📊 Extraindo estatísticas base do canal...")
        canal_info = youtube_data.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()
        playlist_uploads = canal_info['items'][0]['contentDetails']['relatedPlaylists']['uploads']

        if sinal_progresso: sinal_progresso.emit("🕵️‍♂️ Puxando lista de vídeos elegíveis...")
        playlist_resposta = youtube_data.playlistItems().list(part="snippet", playlistId=playlist_uploads, maxResults=12).execute()
        video_ids = [item['snippet']['resourceId']['videoId'] for item in playlist_resposta.get('items', [])]
        
        if not video_ids: return {"aviso": "Nenhum vídeo encontrado no canal."}

        agora_utc = datetime.now(timezone.utc)
        stats_resposta = youtube_data.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute()

        if sinal_progresso: sinal_progresso.emit("📈 Extraindo Retenção e Dados Secretos do Analytics[cite: 1]...")
        hoje = agora_utc.strftime('%Y-%m-%d')
        trinta_dias_atras = (agora_utc - timedelta(days=30)).strftime('%Y-%m-%d')
        
        analytics_map = {}
        try:
            analytics_resposta = youtube_analytics.reports().query(
                ids='channel==MINE',
                startDate=trinta_dias_atras,
                endDate=hoje,
                metrics='views,averageViewDuration',
                dimensions='video',
                filters=f'video=={",".join(video_ids[:10])}'
            ).execute()
            
            for row in analytics_resposta.get('rows', []):
                analytics_map[row[0]] = {
                    "views_30d": row[1],
                    "retencao_media_segundos": row[2]
                }
        except Exception as e:
            if sinal_progresso: sinal_progresso.emit(f"⚠️ Aviso Analytics: {str(e)}")

        videos_detalhados = []
        tema_geral_canal = "Conteúdo Geral"
        
        for idx, item in enumerate(stats_resposta.get('items', [])):
            vid_id = item['id']
            snippet = item['snippet']
            stats = item['statistics']
            
            if idx == 0:
                tema_geral_canal = snippet.get('title', 'Geral')

            if vid_id in historico_otimizacoes:
                dias_mod = (agora_utc - datetime.fromisoformat(historico_otimizacoes[vid_id])).days
                if dias_mod < DIAS_DE_COOLDOWN: continue 

            idade_texto, idade_dias = self.calcular_idade_video(snippet['publishedAt'])
            dados_analytics = analytics_map.get(vid_id, {})
            retencao = dados_analytics.get("retencao_media_segundos", "N/D")

            videos_detalhados.append({
                "id_video": vid_id,
                "titulo_atual": snippet.get('title', ''),
                "descricao_atual": snippet.get('description', ''),
                "idade_do_video": idade_texto,
                "visualizacoes_totais": stats.get('viewCount', '0'),
                "retencao_media_segundos": retencao
            })

        if not videos_detalhados:
            return {"aviso": "Todos os seus vídeos estão no período de maturação do algoritmo (Cooldown de 15 dias)."}

        # Varredura de mercado em alta via YouTube API
        tendencias_mercado = self.buscar_tendencias_youtube_publicas(tema_geral_canal[:30], sinal_progresso)

        ano_atual = datetime.now().year
        if sinal_progresso: sinal_progresso.emit("🔥 Gemini cruzando Analytics, Descrições e Concorrentes em Alta...")

        prompt = f"""
        Atue como o maior Especialista em Algoritmo e SEO do YouTube em {ano_atual}.
        Você tem os dados do Analytics e as descrições atuais dos vídeos do canal.
        
        DADOS DE TENDÊNCIAS REAIS DO MERCADO (YouTube Data API v3):
        {json.dumps(tendencias_mercado, ensure_ascii=False, indent=2)}
        
        REGRA MESTRA DO ALGORITMO:
        - Analise o Título e a Descrição atual de cada vídeo junto com sua Retenção e Views.
        - Se a retenção for boa mas views baixas = Erro de Título/Capa (CTR).
        - Se retenção e views forem ruins = Conteúdo flopado, necessitando de uma nova descrição rica, natural e otimizada com palavras-chave de cauda longa real (5 a 8 palavras).
        - PROIBIDO NEGRITO (**). Use emojis temáticos humanos na nova descrição.

        VÍDEOS ELEGÍVEIS PARA CIRURGIA:
        {json.dumps(videos_detalhados, ensure_ascii=False, indent=2)}

        Retorne ESTRITAMENTE em formato JSON estruturado assim:
        {{
          "diagnostico_geral": "Diagnóstico cirúrgico detalhado...",
          "videos_para_otimizar": [
            {{
              "id_video": "id",
              "titulo_antigo": "Titulo antigo",
              "motivo_do_flop": "Justificativa técnica...",
              "sugestao_novo_titulo_viral": "Novo título sem negrito",
              "sugestao_nova_descricao": "Nova descrição completa, massiva, natural, otimizada com palavras-chave e recheada de emojis temáticos, usando \\n para quebras de linha",
              "sugestao_novas_tags": ["tag1", "tag2", "tag curta", "termo medio composto", "frase de cauda longa real com cinco palavras"]
            }}
          ]
        }}
        """
        
        resposta_json = self.rotacionar_gemini(prompt)
        if sinal_progresso: sinal_progresso.emit("✅ Auditoria Nível Enterprise Concluída!")
        return json.loads(resposta_json)