import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client
from agente import processar_post, gerar_mensagem, verificar_limite
import threading

load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

app = Flask(__name__)
CORS(app)

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

def get_workspace(req):
    token = req.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return None
    try:
        result = supabase.table("workspaces").select("*").eq("token", token).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"get_workspace erro: {e}")
        return None

# ──────────────────────────────────────────────
# HELPER IA — classificar DM
# ──────────────────────────────────────────────
def classificar_mensagem_ia(mensagem: str, nicho: str, tom: str, produto: str) -> dict:
    """Classifica DM com Claude e retorna dados do lead"""
    try:
        import anthropic
        import json
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""Analise essa DM do Instagram e classifique como lead.
Nicho: {nicho}
Produto: {produto}

Mensagem recebida: "{mensagem}"

Responda APENAS em JSON:
{{
  "eh_lead": true/false,
  "nome_detectado": "nome se mencionado ou null",
  "nicho_detectado": "nicho identificado",
  "resumo": "resumo em 1 linha do interesse",
  "confianca": 0.0 a 1.0
}}"""
            }]
        )
        texto = response.content[0].text.strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        return json.loads(texto)
    except Exception as e:
        print(f"Erro IA: {e}")
        return {"eh_lead": True, "nome_detectado": None, "nicho_detectado": nicho, "resumo": mensagem[:100], "confianca": 0.5}

# ──────────────────────────────────────────────
# HELPER — processar DM em background
# ──────────────────────────────────────────────
def processar_dm_webhook(page_id: str, sender_id: str, mensagem: str, timestamp: str):
    """Processa DM recebida via webhook em background"""
    try:
        ws_result = supabase.table("workspaces")\
            .select("*")\
            .eq("instagram_page_id", page_id)\
            .execute()

        if not ws_result.data:
            print(f"Workspace não encontrado para page_id: {page_id}")
            return

        ws = ws_result.data[0]
        nicho   = ws.get("nicho", "marketing digital")
        tom     = ws.get("tom", "profissional e amigável")
        produto = ws.get("produto", "nosso produto")

        classificacao = classificar_mensagem_ia(mensagem, nicho, tom, produto)

        if not classificacao.get("eh_lead", False):
            print(f"Mensagem não classificada como lead: {mensagem[:50]}")
            return

        lead = {
            "workspace_id": ws["id"],
            "nome": classificacao.get("nome_detectado") or sender_id,
            "username_instagram": sender_id,
            "mensagem": mensagem,
            "nicho_detectado": classificacao.get("nicho_detectado", nicho),
            "resumo_ia": classificacao.get("resumo", ""),
            "confianca_ia": classificacao.get("confianca", 0.5),
            "status": "novo",
            "origem": "instagram_dm",
            "created_time": timestamp
        }

        supabase.table("leads").insert(lead).execute()
        print(f"Lead salvo: {sender_id} — {classificacao.get('resumo', '')}")

    except Exception as e:
        print(f"Erro ao processar DM: {e}")

# ──────────────────────────────────────────────
# ROTAS
# ──────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "app": "LeadBot Pro"})

@app.route("/api/status", methods=["GET"])
def status():
    ws = get_workspace(request)
    if not ws:
        return jsonify({"erro": "Não autorizado"}), 401
    limite = verificar_limite(ws["id"])
    return jsonify({
        "workspace": ws["nome"],
        "plano": ws["plano"],
        **limite
    })

@app.route("/api/leads", methods=["GET"])
def listar_leads():
    ws = get_workspace(request)
    if not ws:
        return jsonify({"erro": "Não autorizado"}), 401
    leads = supabase.table("leads")\
        .select("*")\
        .eq("workspace_id", ws["id"])\
        .order("created_time", desc=True)\
        .execute()
    return jsonify(leads.data)

@app.route("/api/gerar-mensagem", methods=["POST"])
def gerar():
    ws = get_workspace(request)
    if not ws:
        return jsonify({"erro": "Não autorizado"}), 401
    limite = verificar_limite(ws["id"])
    if not limite["permitido"]:
        return jsonify({"erro": limite["motivo"]}), 429
    data = request.json
    nome       = data.get("nome", "amigo")
    comentario = data.get("comentario", "")
    mensagem   = gerar_mensagem(nome, comentario, ws["id"])
    return jsonify({"mensagem": mensagem})

@app.route("/api/processar", methods=["POST"])
def processar():
    ws = get_workspace(request)
    if not ws:
        return jsonify({"erro": "Não autorizado"}), 401
    data    = request.json
    post_id = data.get("post_id")
    if not post_id:
        return jsonify({"erro": "post_id obrigatório"}), 400
    resultado = processar_post(post_id, ws["id"])
    return jsonify(resultado)

# ──────────────────────────────────────────────
# WEBHOOK INSTAGRAM — único, sem duplicatas
# ──────────────────────────────────────────────
@app.route("/webhook/instagram", methods=["GET"])
def webhook_verify():
    """Verificação do webhook pelo Meta"""
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    verify_token = os.getenv("SECRET_KEY", "leadbot-pro-secret-2024")

    if mode == "subscribe" and token == verify_token:
        print("Webhook verificado!")
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook/instagram", methods=["POST"])
def webhook_receive():
    """Recebe eventos de DM do Instagram"""
    data = request.json

    if not data:
        return "OK", 200

    try:
        for entry in data.get("entry", []):
            page_id = entry.get("id")

            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message   = messaging.get("message", {})
                text      = message.get("text", "")
                timestamp = messaging.get("timestamp", "")

                if not text or sender_id == page_id:
                    continue

                thread = threading.Thread(
                    target=processar_dm_webhook,
                    args=(page_id, sender_id, text, str(timestamp))
                )
                thread.daemon = True
                thread.start()

    except Exception as e:
        print(f"Erro no webhook: {e}")

    return "OK", 200

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 LeadBot Pro API iniciando na porta 5000...")
    app.run(debug=True, host="0.0.0.0", port=5000)