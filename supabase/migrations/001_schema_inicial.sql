-- =============================================
-- LEADBOT PRO — Schema Multi-tenant
-- =============================================

-- 1. WORKSPACES (cada cliente = 1 workspace)
CREATE TABLE IF NOT EXISTS workspaces (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  nome        TEXT NOT NULL,
  email       TEXT NOT NULL UNIQUE,
  plano       TEXT DEFAULT 'starter' CHECK (plano IN ('starter','pro','agency')),
  token       TEXT UNIQUE DEFAULT gen_random_uuid()::text,
  nicho       TEXT DEFAULT 'marketing digital',
  tom         TEXT DEFAULT 'profissional e amigável',
  produto     TEXT DEFAULT 'nosso produto',
  leads_mes   INT DEFAULT 0,
  ativo       BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 2. LEADS (vinculados ao workspace)
CREATE TABLE IF NOT EXISTS leads (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id     UUID REFERENCES workspaces(id) ON DELETE CASCADE,
  nome             TEXT,
  username         TEXT,
  comentario       TEXT,
  mensagem_gerada  TEXT,
  post_id          TEXT,
  status           TEXT DEFAULT 'novo' CHECK (status IN ('novo','enviado','respondido','convertido')),
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- 3. CHAT MESSAGES (histórico do agente)
CREATE TABLE IF NOT EXISTS chat_messages (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id  UUID REFERENCES workspaces(id) ON DELETE CASCADE,
  lead_id       UUID REFERENCES leads(id) ON DELETE SET NULL,
  role          TEXT CHECK (role IN ('user','assistant')),
  content       TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 4. AGENT STATS (métricas por workspace)
CREATE TABLE IF NOT EXISTS agent_stats (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id  UUID REFERENCES workspaces(id) ON DELETE CASCADE,
  total_leads   INT DEFAULT 0,
  leads_mes     INT DEFAULT 0,
  convertidos   INT DEFAULT 0,
  mes_ref       TEXT DEFAULT TO_CHAR(NOW(), 'YYYY-MM'),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 5. FUNÇÃO: incrementar leads do workspace
CREATE OR REPLACE FUNCTION incrementar_leads(ws_id UUID)
RETURNS void AS $$
BEGIN
  UPDATE workspaces
  SET leads_mes = leads_mes + 1
  WHERE id = ws_id;

  INSERT INTO agent_stats (workspace_id, total_leads, leads_mes)
  VALUES (ws_id, 1, 1)
  ON CONFLICT (workspace_id)
  DO UPDATE SET
    total_leads = agent_stats.total_leads + 1,
    leads_mes   = agent_stats.leads_mes + 1,
    updated_at  = NOW();
END;
$$ LANGUAGE plpgsql;

-- 6. WORKSPACE DE TESTE (seu acesso inicial)
INSERT INTO workspaces (nome, email, plano, nicho, tom, produto)
VALUES (
  'Meu Workspace',
  'admin@leadbotpro.com',
  'agency',
  'marketing digital',
  'profissional e direto',
  'LeadBot Pro — prospecção automática no Instagram'
) ON CONFLICT DO NOTHING;

-- 7. RLS — Row Level Security (cada workspace vê só os seus dados)
ALTER TABLE leads         ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_stats   ENABLE ROW LEVEL SECURITY;

