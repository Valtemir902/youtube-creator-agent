from pathlib import Path

path = Path('src/creator_service/web/dashboard.html')
text = path.read_text(encoding='utf-8')
text = text.replace('id="profileConnectionText"', 'id="ytStatus"', 1)
text = text.replace("$('profileConnectionText')", "$('ytStatus')")
path.write_text(text, encoding='utf-8')
