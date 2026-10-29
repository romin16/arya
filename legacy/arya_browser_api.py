import asyncio
import subprocess
import httpx
import os
from fastapi import FastAPI
from pydantic import BaseModel
from browser_use import Agent, Browser
from browser_use.browser.profile import BrowserProfile
from browser_use.llm import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEBUG_PROFILE = r"C:\Users\abc\chrome-debug-profile"
CDP_PORT = 9222


# ── Request schema ────────────────────────────────────────────────────────────
class TaskRequest(BaseModel):
    task: str  # n8n sends this


# ── Chrome launcher ───────────────────────────────────────────────────────────
async def launch_chrome_if_needed():
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://localhost:{CDP_PORT}/json", timeout=2.0)
            if resp.status_code == 200:
                return  # Already running
    except Exception:
        pass

    subprocess.run("taskkill /F /IM chrome.exe /T", shell=True, capture_output=True)
    await asyncio.sleep(2)

    subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={DEBUG_PROFILE}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
    ])

    for i in range(15):
        await asyncio.sleep(1)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://localhost:{CDP_PORT}/json", timeout=2.0)
                if resp.status_code == 200:
                    return
        except Exception:
            pass

    raise RuntimeError("Chrome failed to start")


# ── Main endpoint — n8n calls this ───────────────────────────────────────────
@app.post("/run-task")
async def run_task(request: TaskRequest):
    try:
        await launch_chrome_if_needed()

        profile = BrowserProfile(cdp_url=f"http://localhost:{CDP_PORT}")
        browser = Browser(browser_profile=profile)
        llm = ChatOpenAI(model="gpt-4.1-mini", api_key=os.getenv("OPENAI_API_KEY"))

        agent = Agent(
            task=request.task,
            llm=llm,
            browser=browser,
            max_actions_per_step=3,
            max_steps=10,
            validate_output=False,  # disables judge — saves tokens + stops false failures
        )

        history = await agent.run(max_steps=10)
        result = history.final_result()

        return {
            "success": True,
            "result": result,
            "task": request.task,
        }

    except Exception as e:
        return {
            "success": False,
            "result": str(e),
            "task": request.task,
        }


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ── Run server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)