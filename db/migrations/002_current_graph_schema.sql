-- Extend the original Phase 1 stores without dropping user data.
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS user_id text;
UPDATE knowledge_chunks kc SET user_id=kd.user_id
 FROM knowledge_docs kd WHERE kc.doc_id=kd.id AND kc.user_id IS NULL;
UPDATE knowledge_chunks SET user_id='legacy-migration' WHERE user_id IS NULL;
ALTER TABLE knowledge_chunks ALTER COLUMN user_id SET NOT NULL;

ALTER TABLE procedures ADD COLUMN IF NOT EXISTS confidence real NOT NULL DEFAULT 0.3;
ALTER TABLE procedures ADD COLUMN IF NOT EXISTS argument_constraints jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE procedures ADD COLUMN IF NOT EXISTS inactive_at timestamptz;
UPDATE procedures SET inactive_at=created_at WHERE active=false AND inactive_at IS NULL;
UPDATE procedures SET severity='soft',confidence=LEAST(confidence,0.3)
 WHERE severity='hard'
   AND rule_text !~* '^\s*(please\s+)?(remember(\s+as\s+a\s+rule)?[:,]?\s*)?(from\s+now\s+on[:,]?\s*|going\s+forward[:,]?\s*)?(never|do\s+not|don''t)\s+(message|text|contact|email|call|recommend|suggest|share|send|tell|mention|use|book|schedule)\b';
UPDATE procedures SET
 tool_pattern=CASE WHEN rule_text ~* '\b(call)\b.*\bwhatsapp\b' THEN 'whatsapp_voice_call' ELSE 'whatsapp_send' END,
 argument_constraints=CASE
   WHEN regexp_match(rule_text,'(?i)(?:message|text|contact)\s+(.+?)\s+(?:on|via)\s+whatsapp') IS NOT NULL
   THEN jsonb_build_array(jsonb_build_object(
     'argument','contact','operator','contains_casefold',
     'value',btrim((regexp_match(rule_text,'(?i)(?:message|text|contact)\s+(.+?)\s+(?:on|via)\s+whatsapp'))[1])))
   ELSE '[]'::jsonb
 END
 WHERE active=true AND coalesce(tool_pattern,'')=''
   AND rule_text ~* '\bwhatsapp\b' AND rule_text ~* '\b(message|text|contact|call|send)\b';
WITH ranked AS (
 SELECT id,row_number() OVER (
   PARTITION BY user_id,lower(btrim(regexp_replace(regexp_replace(btrim(rule_text),'[^[:alnum:]_]+',' ','g'),'\s+',' ','g'))),
                lower(coalesce(tool_pattern,'')),lower(btrim(coalesce(scope,'global')))
   ORDER BY (severity='hard') DESC,confidence DESC,created_at,id
 ) AS position
 FROM procedures WHERE active=true
)
UPDATE procedures p SET active=false,inactive_at=coalesce(p.inactive_at,now()) FROM ranked r WHERE p.id=r.id AND r.position>1;
UPDATE entities e SET valid_to=now()
 WHERE e.valid_to IS NULL
   AND (e.key ~* '(^|_)(rule|procedure|policy)$'
        OR EXISTS (
          SELECT 1 FROM procedures p
          WHERE p.user_id=e.user_id AND p.active=true AND p.rule_text ~* '\bwhatsapp\b'
            AND ((length(btrim(e.key))>1 AND position(lower(btrim(e.key)) IN lower(p.rule_text))>0)
                 OR (jsonb_typeof(e.value)='string' AND length(e.value #>> '{}')>1
                     AND position(lower(e.value #>> '{}') IN lower(p.rule_text))>0))
        ));
CREATE INDEX IF NOT EXISTS procedures_user_active ON procedures(user_id,active);
CREATE UNIQUE INDEX IF NOT EXISTS procedures_active_identity
 ON procedures(user_id,
   (lower(btrim(regexp_replace(regexp_replace(btrim(rule_text),'[^[:alnum:]_]+',' ','g'),'\s+',' ','g')))),
   (lower(coalesce(tool_pattern,''))),
   (lower(btrim(coalesce(scope,'global'))))) WHERE active=true;

ALTER TABLE patterns ADD COLUMN IF NOT EXISTS pattern_key text;
UPDATE patterns SET pattern_key=md5(trim(regexp_replace(regexp_replace(lower(text),'[^[:alnum:]_]+',' ','g'),'\s+',' ','g'))) WHERE pattern_key IS NULL;
WITH ranked AS (
 SELECT id,first_value(id) OVER (PARTITION BY user_id,pattern_key ORDER BY confidence DESC,evidence_count DESC,id) AS keeper,
        sum(evidence_count) OVER (PARTITION BY user_id,pattern_key) AS evidence,
        max(confidence) OVER (PARTITION BY user_id,pattern_key) AS confidence
 FROM patterns WHERE status='active'
), keepers AS (
 UPDATE patterns p SET evidence_count=r.evidence,confidence=r.confidence
 FROM ranked r WHERE p.id=r.keeper RETURNING p.id
)
UPDATE patterns p SET status='merged' FROM ranked r WHERE p.id=r.id AND r.id<>r.keeper;
CREATE UNIQUE INDEX IF NOT EXISTS patterns_active_identity ON patterns(user_id,pattern_key) WHERE status='active';
CREATE TABLE IF NOT EXISTS pattern_observations (
 id bigserial PRIMARY KEY,user_id text NOT NULL,pattern_key text NOT NULL,text text NOT NULL,
 observation_day date NOT NULL,observation_count integer NOT NULL DEFAULT 1,
 first_seen timestamptz NOT NULL DEFAULT now(),last_seen timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,pattern_key,observation_day));
CREATE INDEX IF NOT EXISTS pattern_observations_user_key ON pattern_observations(user_id,pattern_key);
CREATE INDEX IF NOT EXISTS patterns_vec ON patterns USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS patterns_user_status ON patterns(user_id,status);
CREATE INDEX IF NOT EXISTS entities_user_current ON entities(user_id,key) WHERE valid_to IS NULL;

CREATE TABLE IF NOT EXISTS memory_tombstones (
 id bigserial PRIMARY KEY,user_id text NOT NULL,store text NOT NULL,
 fingerprint text NOT NULL,normalized_content text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),suppressed_until timestamptz NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS memory_tombstones_identity ON memory_tombstones(user_id,store,fingerprint);
CREATE INDEX IF NOT EXISTS memory_tombstones_expiry ON memory_tombstones(user_id,suppressed_until);
CREATE TABLE IF NOT EXISTS pending_operations (
 id bigserial PRIMARY KEY,user_id text NOT NULL,thread_id text NOT NULL,
 operation_type text NOT NULL,payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL,
 UNIQUE(user_id,thread_id));
CREATE INDEX IF NOT EXISTS pending_operations_expiry ON pending_operations(expires_at);

ALTER TABLE action_log ADD COLUMN IF NOT EXISTS tool_call_id text;
ALTER TABLE action_log ADD COLUMN IF NOT EXISTS approved_at timestamptz;
ALTER TABLE action_log ADD COLUMN IF NOT EXISTS approval_channel text;
CREATE UNIQUE INDEX IF NOT EXISTS action_log_thread_tool_call_id
 ON action_log(thread_id,tool_call_id) WHERE tool_call_id IS NOT NULL;
