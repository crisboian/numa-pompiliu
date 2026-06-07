# Patch script: fix rag_reindex_all to pass db to rag_reindex
import re

with open("/home/claude/numa-cloud/backend/server.py", "r") as f:
    content = f.read()

# Fix 1: Add db parameter to rag_reindex_all
old = """@app.post("/api/rag/reindex/all")
async def rag_reindex_all():"""
new = """@app.post("/api/rag/reindex/all")
async def rag_reindex_all(db: AsyncSession = Depends(get_db)):"""
content = content.replace(old, new)

# Fix 2: Pass db when calling rag_reindex()
old = """    return await rag_reindex()"""
new = """    return await rag_reindex(db)"""
content = content.replace(old, new)

with open("/home/claude/numa-cloud/backend/server.py", "w") as f:
    f.write(content)

print("Patched")
