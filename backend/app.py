import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client
from agente import processar_post, gerar_mensagem, verificar_limite

load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

app = Flask(__name__)
CORS(app)

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def get_workspace(req):
    token = req.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return None
    ws = supabase.table("workspaces").select("*").eq("token", token).single().execute()
    return ws.data if ws.data else None

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
        .order("created_at", desc=True)\
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
    nome = data.get("nome", "amigo")
    comentario = data.get("comentario", "")
    mensagem = gerar_mensagem(nome, comentario, ws["id"])
    return jsonify({"mensagem": mensagem})

@app.route("/api/processar", methods=["POST"])
def processar():
    ws = get_workspace(request)
    if not ws:
        return jsonify({"erro": "Não autorizado"}), 401
    data = request.json
    post_id = data.get("post_id")
    if not post_id:
        return jsonify({"erro": "post_id obrigatório"}), 400
    resultado = processar_post(post_id, ws["id"])
    return jsonify(resultado)

if __name__ == "__main__":
    print("🚀 LeadBot Pro API iniciando na porta 5000...")
    app.run(debug=True, host="0.0.0.0", port=5000)
