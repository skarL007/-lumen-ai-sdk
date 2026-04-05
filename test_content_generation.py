import json

class ContentAgencyTester:
    """Simula a geração de conteúdo de alta conversão da Noctra Agency."""

    def generate_blog_post(self):
        return {
            "title": "FinOps de IA: Como não quebrar sua startup com custos de API",
            "hook": "Você acabou de lançar seu agente de IA. O tráfego está subindo. Mas, de repente, a conta da OpenAI chega em $2.000. O que aconteceu?",
            "body": "No mundo da IA Generativa, observabilidade técnica não é suficiente. Você precisa de FinOps. O LumenAI foi criado para iluminar os custos invisíveis de cada span, isolando por cliente (Tenant) e calculando o ROI em tempo real. \n\nNeste artigo, exploramos como o LumenAI utiliza OpenTelemetry para transformar traces confusos em métricas de faturamento precisas.",
            "cta": "Leia o guia completo no nosso GitHub: github.com/skarL007/-lumen-ai-sdk",
            "tags": ["AI", "FinOps", "Python", "Startup"]
        }

    def generate_insta_carousel(self):
        return [
            {"slide": 1, "headline": "IA é cara. Mas não precisa ser cega. 🔦", "visual": "Logo LumenAI Neon em fundo escuro."},
            {"slide": 2, "headline": "O Problema: Custos Invisíveis.", "visual": "Gráfico de custos subindo sem controle."},
            {"slide": 3, "headline": "A Solução: LumenAI SDK.", "visual": "Screenshot do nosso Simulador Visual (lumen-preview.png)."},
            {"slide": 4, "headline": "Multi-tenancy Nativo.", "visual": "Diagrama mostrando Cliente A e Cliente B isolados."},
            {"slide": 5, "headline": "Comece hoje. É Grátis.", "visual": "Botão de Sponsor do GitHub piscando."}
        ]

    def run_test(self):
        print("\n--- 📝 TESTE DE CONTEÚDO PARA BLOG ---")
        blog = self.generate_blog_post()
        print(f"Título: {blog['title']}\n")
        print(f"Hook: {blog['hook']}\n")
        print(f"CTA: {blog['cta']}\n")

        print("\n--- 📸 TESTE DE CONTEÚDO PARA INSTAGRAM (CARROSSEL) ---")
        carousel = self.generate_insta_carousel()
        for s in carousel:
            print(f"Slide {s['slide']}: {s['headline']} | Visual: {s['visual']}")

if __name__ == "__main__":
    tester = ContentAgencyTester()
    tester.run_test()
