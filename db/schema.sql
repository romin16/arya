CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS entities (
 id bigserial PRIMARY KEY, user_id text NOT NULL, key text NOT NULL, value jsonb NOT NULL,
 confidence real DEFAULT 1.0, source text, valid_from timestamptz DEFAULT now(), valid_to timestamptz,
 superseded_by bigint REFERENCES entities(id));
CREATE UNIQUE INDEX IF NOT EXISTS entities_current ON entities(user_id,key) WHERE valid_to IS NULL;

CREATE TABLE IF NOT EXISTS episodes (
 id bigserial PRIMARY KEY,user_id text NOT NULL,thread_id text,ts timestamptz DEFAULT now(),
 summary text,body text,embedding vector(1536),topics text[],tools_used text[],
 tsv tsvector GENERATED ALWAYS AS (to_tsvector('english',coalesce(summary,'')||' '||coalesce(body,''))) STORED);
CREATE INDEX IF NOT EXISTS episodes_vec ON episodes USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS episodes_tsv ON episodes USING gin(tsv);

CREATE TABLE IF NOT EXISTS knowledge_docs (id bigserial PRIMARY KEY,user_id text NOT NULL,title text,source text,created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS knowledge_chunks (
 id bigserial PRIMARY KEY,user_id text NOT NULL,doc_id bigint REFERENCES knowledge_docs(id) ON DELETE CASCADE,
 chunk_idx int,text text,embedding vector(1536),metadata jsonb,
 tsv tsvector GENERATED ALWAYS AS (to_tsvector('english',coalesce(text,''))) STORED);
CREATE INDEX IF NOT EXISTS kc_vec ON knowledge_chunks USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS kc_tsv ON knowledge_chunks USING gin(tsv);

CREATE TABLE IF NOT EXISTS procedures (
 id bigserial PRIMARY KEY,user_id text NOT NULL,rule_text text NOT NULL,scope text DEFAULT 'global',
 tool_pattern text,severity text CHECK(severity IN ('hard','soft')),active boolean DEFAULT true,created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS patterns (
 id bigserial PRIMARY KEY,user_id text NOT NULL,text text NOT NULL,evidence_count int DEFAULT 1,
 confidence real,status text DEFAULT 'active',first_seen timestamptz DEFAULT now(),last_seen timestamptz DEFAULT now(),embedding vector(1536));
CREATE INDEX IF NOT EXISTS patterns_vec ON patterns USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS patterns_user_status ON patterns(user_id,status);
CREATE INDEX IF NOT EXISTS entities_user_current ON entities(user_id,key) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS procedures_user_active ON procedures(user_id,active);
CREATE TABLE IF NOT EXISTS action_log (
 id bigserial PRIMARY KEY,user_id text NOT NULL,thread_id text,ts timestamptz DEFAULT now(),tool text,
 args jsonb,status text,result_summary text,approved_by text,duration_ms int);
CREATE TABLE IF NOT EXISTS pii_vault (
 token text PRIMARY KEY,kind text NOT NULL,value_enc bytea NOT NULL,created_at timestamptz DEFAULT now());
