import os
import requests
import anthropic
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# Clientes
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
claude   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

INSTAGRAM_TOKEN   = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_PAGE_ID = os.getenv("INSTAGRAM_PAGE_ID")

# ──────────────────────────────────────────────
# 1. BUSCAR COMENTÁRIOS DO INSTAGRAM
# ──────────────────────────────────────────────
def buscar_comentarios(post_id: str):
    url = f"https://graph.facebook.com/v19.0/{post_id}/comments"
    params = {
        "fields": "id,text,username,timestamp",
        "access_token": INSTAGRAM_TOKEN
    }
    resp = requests.get(url, params=params)
    data = resp.json()
    return data.get("data", [])

# ──────────────────────────────────────────────
# 2. GERAR MENSAGEM COM CLAUDE
# ──────────────────────────────────────────────
def gerar_mensagem(nome: str, comentario: str, workspace_id: str) -> str:
    # Buscar configuração do workspace (nicho, tom)
    config = supabase.table("workspaces")\
        .select("nicho, tom, produto")\
        .eq("id", workspace_id)\
        .single()\
        .execute()

    nicho   = config.data.get("nicho", "marketing digital") if config.data else "marketing digital"
    tom     = config.data.get("tom", "profissional e amigável") if config.data else "profissional e amigável"
    produto = config.data.get("produto", "nosso produto") if config.data else "nosso produto"

    prompt = f"""Você é um especialista em prospecção para Instagram no nicho de {nicho}.

Crie uma mensagem direta (DM) personalizada para um lead chamado {nome} que comentou:
"{comentario}"

Tom: {tom}
Produto/serviço: {produto}

Regras:
- Máximo 3 parágrafos curtos
- Mencione o comentário da pessoa naturalmente
- Termine com uma CTA clara (chamada para ação)
- NÃO pareça robótico ou genérico
- Escreva em português brasileiro"""

    resp = claude.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text

# ──────────────────────────────────────────────
# 3. SALVAR LEAD NO SUPABASE
# ──────────────────────────────────────────────
def salvar_lead(workspace_id: str, nome: str, username: str,
                comentario: str, mensagem: str, post_id: str):
    lead = {
        "workspace_id": workspace_id,
        "nome": nome,
        "username": username,
        "comentario": comentario,
        "mensagem_gerada": mensagem,
        "post_id": post_id,
        "status": "novo",
        "created_at": datetime.utcnow().isoformat()
    }
    result = supabase.table("leads").insert(lead).execute()
    return result.data

# ──────────────────────────────────────────────
# 4. VERIFICAR LIMITE DO PLANO
# ──────────────────────────────────────────────
def verificar_limite(workspace_id: str) -> dict:
    ws = supabase.table("workspaces")\
        .select("plano, leads_mes")\
        .eq("id", workspace_id)\
        .single()\
        .execute()

    if not ws.data:
        return {"permitido": False, "motivo": "Workspace não encontrado"}

    limites = {"starter": 50, "pro": 200, "agency": 999999}
    plano   = ws.data.get("plano", "starter")
    usados  = ws.data.get("leads_mes", 0)
    limite  = limites.get(plano, 50)

    if usados >= limite:
        return {
            "permitido": False,
            "motivo": f"Limite do plano {plano} atingido ({limite} leads/mês)",
            "upgrade_url": "https://leadbotpro.com/upgrade"
        }
    return {"permitido": True, "usados": usados, "limite": limite}

# ──────────────────────────────────────────────
# 5. PROCESSAR POST COMPLETO
# ──────────────────────────────────────────────
def processar_post(post_id: str, workspace_id: str) -> dict:
    print(f"\n🚀 Processando post {post_id} para workspace {workspace_id}")

    # Verificar limite antes
    limite = verificar_limite(workspace_id)
    if not limite["permitido"]:
        print(f"❌ {limite['motivo']}")
        return {"erro": limite["motivo"], "upgrade": limite.get("upgrade_url")}

    comentarios = buscar_comentarios(post_id)
    print(f"📥 {len(comentarios)} comentários encontrados")

    leads_salvos = []
    for c in comentarios:
        try:
            nome     = c.get("username", "amigo")
            texto    = c.get("text", "")
            if not texto:
                continue

            print(f"  → Gerando mensagem para @{nome}...")
            mensagem = gerar_mensagem(nome, texto, workspace_id)
            lead     = salvar_lead(workspace_id, nome, nome, texto, mensagem, post_id)
            leads_salvos.append(lead)

            # Incrementar contador
            supabase.rpc("incrementar_leads", {"ws_id": workspace_id}).execute()

        except Exception as e:
            print(f"  ⚠️ Erro em @{nome}: {e}")
            continue

    print(f"✅ {len(leads_salvos)} leads processados")
    return {
        "total": len(leads_salvos),
        "leads": leads_salvos,
        "workspace_id": workspace_id
    }

# ──────────────────────────────────────────────
# 6. TESTE LOCAL
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 LeadBot Pro — Agente iniciado")
    print(f"📡 Supabase: {os.getenv('SUPABASE_URL')}")
    print(f"📸 Instagram Page: {os.getenv('INSTAGRAM_PAGE_ID')}")
    print("✅ Todas as configurações carregadas!")
