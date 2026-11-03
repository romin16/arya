-- Keep the chunk-level search projection expected by hybrid retrieval.
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS title text;

UPDATE knowledge_chunks AS chunks
SET title = docs.title
FROM knowledge_docs AS docs
WHERE chunks.doc_id = docs.id
  AND chunks.title IS NULL;
