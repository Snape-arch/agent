import os, re

path = r"C:\Users\34712\Desktop\agentwork\clawos\clawos_server.py"
with open(path, encoding="utf-8-sig") as f:
    content = f.read()

# Add g_reflection_engine global
content = content.replace(
    "g_memory_store: Any = None\n",
    "g_memory_store: Any = None\ng_reflection_engine: Any = None\n"
)

# Insert reflection engine init after MemoryOS init
insertion = '''
    global g_reflection_engine
    try:
        from reflection.engine import ReflectionEngine
        g_reflection_engine = ReflectionEngine(g_memory_store, http_client, config.get("routing", {}))
        logger.info("Reflection Engine initialized")
    except Exception as e:
        logger.warning(f"Reflection Engine init skipped: {e}")
        g_reflection_engine = None
'''

marker = 'logger.info(f"ClawOS ready'
content = content.replace(marker, insertion + "\n    " + marker)

# Add API endpoints before main()
api_routes = '''
@app.post("/api/reflection/trigger")
async def trigger_reflection(request: Request):
    if not g_reflection_engine:
        raise HTTPException(503, "Reflection Engine not initialized")
    try:
        body = await request.body()
        req_data = json.loads(body) if body else {}
    except:
        req_data = {}
    sid = req_data.get("session_id", "default")
    task = req_data.get("task", "Manual reflection")
    fb = req_data.get("feedback", "")
    result = g_reflection_engine.reflect("user_triggered", sid, [], fb, task)
    return JSONResponse(result)

@app.get("/api/reflection/list")
async def list_reflections(limit: int = 20):
    if not g_reflection_engine:
        raise HTTPException(503, "Reflection Engine not initialized")
    from reflection.memory_writer import ReflectionMemoryWriter
    writer = ReflectionMemoryWriter(g_memory_store)
    cards = writer.get_reflection_cards(limit)
    return JSONResponse({"cards": cards, "count": len(cards)})

@app.get("/api/reflection/stats")
async def reflection_stats():
    if not g_reflection_engine:
        raise HTTPException(503, "Reflection Engine not initialized")
    from reflection.learning_loop import LearningLoop
    loop = LearningLoop(g_reflection_engine, g_memory_store)
    return JSONResponse(loop.get_cycle_stats())

'''

content = content.replace('def main():', api_routes + '\ndef main():')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Reflection Engine integrated into clawos_server.py")
