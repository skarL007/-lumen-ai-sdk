import json
import urllib.request
import datetime
import os

WEBHOOK_URL = "https://discord.com/api/webhooks/1489638228360429666/r2NlNrUvCpg6ii6s-kZbmZ-KUn6qK62p8tblghp-qeqQQMUpAeC4C18jgeWz7Er8llVl"

def send_review_request(draft_file="draft_post.json"):
    """Envia um rascunho da Claude para validação no Discord."""
    try:
        if not os.path.exists(draft_file):
            print(f"No {draft_file} found. Skipping review.")
            return

        with open(draft_file, "r", encoding="utf-8") as f:
            drafts = json.load(f)

        for i, post in enumerate(drafts):
            payload = {
                "username": "LumenAI Review Bot",
                "embeds": [{
                    "title": f"🚨 REVIEW REQUIRED: Post #{i+1} ({post['platform']})",
                    "url": "https://github.com/skarL007/-lumen-ai-sdk",
                    "description": f"**Content:**\n`{post['content']}`\n\n**Theme:** {post['theme']}",
                    "color": 16766720, # Laranja (Review)
                    "fields": [
                        {
                            "name": "✅ Como aprovar?",
                            "value": "Acesse [GitHub Actions](https://github.com/skarL007/-lumen-ai-sdk/actions) e rode o workflow **LumenAI Manual Post** com este conteúdo.",
                            "inline": False
                        },
                        {
                            "name": "🖥️ Simulador Visual",
                            "value": "[Abrir Demo](https://skarL007.github.io/-lumen-ai-sdk/lumen-demo.html)",
                            "inline": True
                        },
                        {
                            "name": "🐙 Repositório",
                            "value": "[github.com/skarL007/-lumen-ai-sdk](https://github.com/skarL007/-lumen-ai-sdk)",
                            "inline": True
                        }
                    ],
                    "footer": {"text": "Aguardando sua validação, skar1v9! 🔦"}
                }]
            }

            req = urllib.request.Request(WEBHOOK_URL, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                print(f"✅ Review request sent to Discord (Post #{i+1})")
                
    except Exception as e:
        print(f"❌ Error sending review: {e}")

if __name__ == "__main__":
    send_review_request()
