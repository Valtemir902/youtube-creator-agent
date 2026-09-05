import os
import sys
import json
from datetime import datetime
import torch
import whisper
import imageio_ffmpeg
import shutil
import re

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QFrame

import google.generativeai as genai

from analista_metricas import AnalistaCanal
from publicador_youtube import PublicadorYouTube

if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
    BASE_DIR = os.path.dirname(EXE_DIR) if os.path.basename(EXE_DIR) == 'dist' else EXE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASTA_CONFIG = os.path.join(BASE_DIR, "config")
ARQUIVO_TOKEN = os.path.join(PASTA_CONFIG, "token.json")

class DialogoAprovacao(QDialog):
    def __init__(self, dados_seo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Revisão Estratégica - Cauda Longa Real")
        self.setFixedSize(750, 600)
        self.setStyleSheet(parent.styleSheet())

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("🔥 Estratégia Antiflop com Cauda Longa Real Gerada! Revise:"))
        
        self.texto_revisao = QTextEdit()
        self.texto_revisao.setReadOnly(True)
        self.texto_revisao.setObjectName("input_multi")
        
        conteudo = ""
        if "youtube" in dados_seo:
            yt_data = dados_seo["youtube"]
            conteudo += "🔴 OTIMIZAÇÃO DE ELITE (YOUTUBE):\n"
            conteudo += f"📌 TÍTULO PERSUASIVO:\n{yt_data.get('titulos_virais', [''])[0] if isinstance(yt_data.get('titulos_virais'), list) else yt_data.get('titulos_virais', '')}\n\n"
            conteudo += f"📝 DESCRIÇÃO HUMANA E OTIMIZADA:\n{yt_data.get('descricao_seo', '')}\n\n"
            conteudo += f"🏷️ TAGS COM CAUDA LONGA REAL (5 a 8+ palavras):\n{', '.join(yt_data.get('tags', []))}\n"

        self.texto_revisao.setText(conteudo)
        layout.addWidget(self.texto_revisao)

        frame_botoes = QFrame()
        layout_botoes = QHBoxLayout(frame_botoes)
        btn_cancelar = QPushButton("❌ Descartar")
        btn_cancelar.setObjectName("btn_secundario")
        btn_cancelar.clicked.connect(self.reject)
        
        btn_aprovar = QPushButton("🚀 APROVAR E ENVIAR AO YOUTUBE")
        btn_aprovar.setObjectName("btn_primario")
        btn_aprovar.clicked.connect(self.accept)

        layout_botoes.addWidget(btn_cancelar)
        layout_botoes.addWidget(btn_aprovar)
        layout.addWidget(frame_botoes)

class DialogoAuditoria(QDialog):
    def __init__(self, dados_auditoria, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cirurgia de Canal - Reestruturação SEO")
        self.setFixedSize(750, 650)
        self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("🩺 Diagnóstico Profundo do Canal e Cirurgia de SEO:"))
        
        self.texto_revisao = QTextEdit()
        self.texto_revisao.setReadOnly(True)
        self.texto_revisao.setObjectName("input_multi")
        
        conteudo = f"📊 DIAGNÓSTICO GERAL:\n{dados_auditoria.get('diagnostico_geral', 'N/D')}\n\n"
        videos_arrumar = dados_auditoria.get('videos_para_otimizar', [])
        
        if not videos_arrumar:
            conteudo += "✅ Todos os vídeos estão com alta performance!"
        else:
            conteudo += "🛠️ VÍDEOS QUE EXIGEM CORREÇÃO IMEDIATA:\n"
            for v in videos_arrumar:
                conteudo += f"\n❌ Título Antigo: {v.get('titulo_antigo')}\n"
                conteudo += f"⚠️ Motivo do Flop: {v.get('motivo_do_flop')}\n"
                conteudo += f"✅ NOVO Título: {v.get('sugestao_novo_titulo_viral')}\n"
                conteudo += f"📝 NOVA Descrição: {v.get('sugestao_nova_descricao', 'Mantida')[:150]}...\n"
                conteudo += f"🏷️ Novas Tags: {', '.join(v.get('sugestao_novas_tags', []))}\n" + "-"*40

        self.texto_revisao.setText(conteudo)
        layout.addWidget(self.texto_revisao)

        # 🟢 CORREÇÃO DOS BOTÕES: Adicionados corretamente ao layout
        frame_botoes = QFrame()
        layout_botoes = QHBoxLayout(frame_botoes)
        
        btn_cancelar = QPushButton("❌ Fechar / Ignorar")
        btn_cancelar.setObjectName("btn_secundario")
        btn_cancelar.clicked.connect(self.reject)
        
        btn_aprovar = QPushButton("💉 APLICAR CIRURGIA DE SEO NOS VÍDEOS")
        btn_aprovar.setObjectName("btn_primario")
        if not videos_arrumar: 
            btn_aprovar.setEnabled(False)
        btn_aprovar.clicked.connect(self.accept)

        layout_botoes.addWidget(btn_cancelar)
        layout_botoes.addWidget(btn_aprovar)
        layout.addWidget(frame_botoes)

class AgenteWorker(QThread):
    progresso_sinal = Signal(str)
    aguardando_aprovacao_sinal = Signal(dict)
    erro_sinal = Signal(str)

    def __init__(self, caminho_video, formato_conteudo, api_keys, arquivo_token):
        super().__init__()
        self.caminho_video = caminho_video
        self.formato_conteudo = formato_conteudo
        self.api_keys = api_keys
        self.arquivo_token = arquivo_token
        self.indice_chave = 0

    def run(self):
        try:
            ffmpeg_original = imageio_ffmpeg.get_ffmpeg_exe()
            pasta_ffmpeg = os.path.dirname(ffmpeg_original)
            ffmpeg_novo = os.path.join(pasta_ffmpeg, "ffmpeg.exe")
            if not os.path.exists(ffmpeg_novo): shutil.copy(ffmpeg_original, ffmpeg_novo)
            if pasta_ffmpeg not in os.environ.get("PATH", ""): os.environ["PATH"] = pasta_ffmpeg + os.pathsep + os.environ.get("PATH", "")

            ano_atual = datetime.now().year
            self.progresso_sinal.emit(f"🧠 [1/3] Extraindo e transcrevendo áudio com Whisper ({ano_atual})...")
            
            dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
            modelo_whisper = whisper.load_model("small", device=dispositivo)
            resultado = modelo_whisper.transcribe(self.caminho_video, language="pt")
            texto_transcrito = resultado["text"]
            self.progresso_sinal.emit("✅ Transcrição concluída!")

            self.progresso_sinal.emit("🔎 [2/3] Varrendo concorrentes em alta via YouTube Data API v3...")
            genai.configure(api_key=self.api_keys[0])
            model_busca = genai.GenerativeModel('gemini-2.5-flash')
            prompt_termo = f"Com base nesta transcrição, extraia APENAS um termo de busca principal de 2 a 4 palavras para pesquisar no YouTube: '{texto_transcrito[:1000]}'"
            termo_pesquisa = model_busca.generate_content(prompt_termo).text.strip().replace('"', '')

            analista = AnalistaCanal(self.arquivo_token, self.api_keys)
            concorrentes_reais = analista.buscar_tendencias_youtube_publicas(termo_pesquisa, self.progresso_sinal)

            self.progresso_sinal.emit("🔥 [3/3] Cérebro Gemini cruzando transcrição e dados reais de mercado...")
            
            if "Curto" in self.formato_conteudo:
                diretriz_formato = "FORMATO: YOUTUBE SHORTS. Título magnético e direto (máx 60 caracteres) contendo #shorts. Descrição curta com emojis."
            else:
                diretriz_formato = "FORMATO: VÍDEO LONGO. Título persuasivo e de alta conversão. Descrição massiva, rica, 100% natural, fluida e humana."

            prompt = f"""
            Atue como o Maior Especialista em SEO e Algoritmo do YouTube em {ano_atual}.
            {diretriz_formato}
            
            DADOS REAIS DE CONCORRENTES EM ALTA:
            {json.dumps(concorrentes_reais, ensure_ascii=False, indent=2)}
            
            REGRAS ABSOLUTAS DE OURO:
            1. ZERO NEGRITO: Proibido o uso de asteriscos duplos (**) em qualquer parte. O texto deve ser limpo.
            2. EMOJIS CONTEXTUAIS: Insira emojis modernos e temáticos do nicho falado no vídeo de forma orgânica na descrição.
            3. ESTRUTURA RIGOROSA DE TAGS (OBRIGATÓRIO CAUDA LONGA REAL DE 5 A 8+ PALAVRAS): 
               Forneça uma lista exata de 25 tags divididas em cauda curta, média e pelo menos 15 caudas longas reais (frases completas de busca).
            4. FORMATO DO JSON: Retorne APENAS um objeto JSON válido, escapando quebras de linha com '\\n'.

            TRANSCRIÇÃO DO VIDEO:
            {texto_transcrito}
            
            ESTRUTURA EXATA DO JSON RETORNADO:
            {{
              "youtube": {{
                "titulos_virais": ["Título principal altamente persuasivo e sem negrito"],
                "descricao_seo": "Sua descrição massiva, natural, rica em valor, recheada de emojis temáticos, sem asteriscos e usando \\n para quebras de linha",
                "tags": [
                  "termo curto 1", "termo curto 2", "termo curto 3", "termo curto 4",
                  "termo medio composto 1", "termo medio composto 2", "termo medio composto 3", "termo medio composto 4", "termo medio composto 5", "termo medio composto 6",
                  "como fazer a gestao financeira completa da fazenda", "qual o melhor metodo para controlar pragas na lavoura", "aplicativo gratuito para controle de insumos agricolas", "como aumentar a produtividade do plantio passo a passo", "segredos da agricultura de precisao para pequenos produtores", "guia definitivo sobre agronomia digital e talhoes", "como emitir laudos agronomicos rapidos direto no celular", "estrategias infaliveis para lucrar mais trabalhando na roça", "como organizar os talhoes e as atividades da propriedade", "tudo sobre tecnologia no campo atualizada para produtores", "como manter todas as financas da fazenda organizadas", "melhor forma de planejar a safra sem gastar muito", "como resolver problemas de doencas nas plantas em tempo real", "ferramentas essenciais para a gestao rural eficiente hoje", "como transformar a administracao do agronegocio digitalmente"
                ]
              }}
            }}
            """
            
            chave = self.api_keys[self.indice_chave]
            genai.configure(api_key=chave)
            model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json", "temperature": 0.3})
            resposta_texto = model.generate_content(prompt).text
            
            try:
                dados_seo = json.loads(resposta_texto)
            except json.JSONDecodeError:
                resposta_limpa = re.sub(r'[\n\r]+', ' ', resposta_texto)
                dados_seo = json.loads(resposta_limpa)

            self.progresso_sinal.emit("⏸️ Otimização concluída. Aguardando sua revisão...")
            self.aguardando_aprovacao_sinal.emit(dados_seo)
        except Exception as e:
            self.erro_sinal.emit(f"❌ Erro Crítico no Motor IA: {str(e)}")

class PublicarWorker(QThread):
    progresso_sinal = Signal(str)
    concluido_sinal = Signal(str)
    erro_sinal = Signal(str)

    def __init__(self, video_path, thumb_path, dados_seo, formato, modo_publicacao):
        super().__init__()
        self.video_path = video_path
        self.thumb_path = thumb_path
        self.dados_seo = dados_seo
        self.formato = formato
        self.modo_publicacao = modo_publicacao

    def run(self):
        try:
            publicar_imediato = (self.modo_publicacao == "⚡ Publicar Agora")
            self.progresso_sinal.emit("🚀 [YouTube] Conectando ao canal...")
            
            publicador_yt = PublicadorYouTube(ARQUIVO_TOKEN)
            video_id = publicador_yt.publicar_novo_conteudo(
                self.video_path, self.dados_seo.get("youtube", {}), self.formato, self.thumb_path, publicar_agora=publicar_imediato
            )
            
            self.concluido_sinal.emit(f"✅ VÍDEO PUBLICADO COM SUCESSO! ID: {video_id}")
        except Exception as e:
            self.erro_sinal.emit(f"❌ Erro na Publicação: {str(e)}")

class AuditoriaWorker(QThread):
    progresso_sinal = Signal(str)
    concluido_sinal = Signal(dict)
    erro_sinal = Signal(str)

    def __init__(self, api_keys, arquivo_token):
        super().__init__()
        self.api_keys = api_keys
        self.arquivo_token = arquivo_token

    def run(self):
        try:
            analista = AnalistaCanal(self.arquivo_token, self.api_keys)
            dados = analista.auditar_canal_profundo(self.progresso_sinal)
            self.concluido_sinal.emit(dados)
        except Exception as e:
            self.erro_sinal.emit(f"❌ Erro na Auditoria: {str(e)}")

class AplicarCirurgiaWorker(QThread):
    progresso_sinal = Signal(str)
    concluido_sinal = Signal(str)
    erro_sinal = Signal(str)

    def __init__(self, videos_para_arrumar, arquivo_token):
        super().__init__()
        self.videos_para_arrumar = videos_para_arrumar
        self.arquivo_token = arquivo_token

    def run(self):
        try:
            publicador = PublicadorYouTube(self.arquivo_token)
            for v in self.videos_para_arrumar:
                vid_id = v.get("id_video")
                novo_titulo = v.get("sugestao_novo_titulo_viral")
                nova_desc = v.get("sugestao_nova_descricao", None)
                novas_tags = v.get("sugestao_novas_tags", [])
                
                self.progresso_sinal.emit(f"🛠️ Aplicando cirurgia corretiva no vídeo {vid_id}...")
                publicador.atualizar_video_existente(vid_id, novo_titulo, novas_tags, nova_desc)
                
            self.concluido_sinal.emit("✅ Todos os vídeos foram curados e otimizados com sucesso!")
        except Exception as e:
            self.erro_sinal.emit(f"❌ Erro na Cirurgia de Vídeo: {str(e)}")

class TrendHunterWorker(QThread):
    progresso_sinal = Signal(str)
    concluido_sinal = Signal(str)
    erro_sinal = Signal(str)

    def __init__(self, nicho, api_keys, arquivo_token):
        super().__init__()
        self.nicho = nicho
        self.api_keys = api_keys
        self.arquivo_token = arquivo_token

    def run(self):
        try:
            self.progresso_sinal.emit(f"🔎 Conectando à YouTube Data API v3 para varrer concorrentes em alta sobre: {self.nicho}...")
            analista = AnalistaCanal(self.arquivo_token, self.api_keys)
            titulos_reais = analista.buscar_tendencias_youtube_publicas(self.nicho, self.progresso_sinal)
            
            self.progresso_sinal.emit("🧠 Cruzando os títulos reais da API com o Gemini para estruturar as tendências...")
            genai.configure(api_key=self.api_keys[0])
            model = genai.GenerativeModel('gemini-2.5-flash')
            ano_atual = datetime.now().year
            
            prompt = f"""
            Atue como o Maior Estrategista de Crescimento do YouTube em {ano_atual}.
            Abaixo estão os títulos reais de vídeos em alta no nicho "{self.nicho}", obtidos diretamente da YouTube Data API v3:
            
            {json.dumps(titulos_reais, ensure_ascii=False, indent=2)}
            
            Com base estritamente nesses dados reais do mercado atual:
            1. Aponte os padrões de títulos e palavras-chave que estão gerando mais visualizações.
            2. Entregue 3 ideias completas de títulos virais altamente persuasivos baseados nessa varredura real.
            3. Sugira termos de cauda longa real (5 a 8 palavras) para dominar a busca orgânica.
            """
            
            resposta = model.generate_content(prompt)
            self.concluido_sinal.emit(resposta.text)
        except Exception as e:
            self.erro_sinal.emit(f"❌ Erro na Varredura Real de Tendências: {str(e)}")