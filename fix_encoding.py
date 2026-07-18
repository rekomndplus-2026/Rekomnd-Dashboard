import sys
p = 'c:/Users/Mostafa Atta/Downloads/New folder/rekomnd_plus/templates/gmaps.html'
with open(p, 'r', encoding='utf-8') as f:
    text = f.read()

replacements = {
    'â€”': '—',
    'ðŸ—º': '🗺️',
    'â†’': '→',
    'â€¦': '…',
    'â†»': '↻',
    'ðŸ” ': '🔍',
    'â¬‡': '⬇',
    'â† ': '←',
    'â”€': '─',
    'Â·': '·',
    'âœ•': '✕',
    'â˜…': '★',
    'â†—': '↗',
    'ðŸ”—': '🔗',
    'ðŸ“ ': '📍',
    'âœ…': '✅',
    'â ¹': '⏹'
}

for k, v in replacements.items():
    text = text.replace(k, v)

with open(p, 'w', encoding='utf-8') as f:
    f.write(text)

print('Done!')
