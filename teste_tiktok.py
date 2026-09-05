import sys
import os

# Mostra para o Python onde está a nossa pasta src
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from publicador_tiktok import PublicadorTikTok

print("🤖 Ligando os motores do TikTok...")
bot = PublicadorTikTok()

try:
    bot.autenticar()
    print("✅ Sucesso Absoluto! O token de acesso foi salvo no cofre.")
except Exception as e:
    print(f"❌ Ops, algo deu errado: {e}")