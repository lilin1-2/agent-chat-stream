"""
Agent 流式对话服务 —— 多轮对话 + Session 隔离 + SSE 流式 + Summary Memory

接口：
  GET  /health              健康检查
  POST /session/create       创建新会话
  GET  /session/list         列出所有会话
  DELETE /session/{id}        删除会话
  GET  /session/{id}/history  查看历史
  POST /chat                  非流式对话
  POST /chat/stream           SSE 流式对话
"""
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import requests
import json
import os
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("app.log", encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("API_KEY")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL")

# API 认证
def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key 无效或缺失")
    return True

from session_store import (
    create_session, get_all_sessions, delete_session,
    get_history, add_message, get_message_count,
    get_summary, save_summary, MAX_HISTORY_MESSAGES
)

app = FastAPI(
    title="Agent 流式对话服务",
    description="多轮对话 + Session 隔离 + SQLite 持久化 + Summary Memory + SSE 流式",
    version="1.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# 数据模型
# ============================================================

class CreateSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=50, description="会话 ID")
    name: str = Field(default="", description="会话名称")


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    message: str = Field(..., min_length=1, max_length=5000, description="用户消息")


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    message_count: int


# ============================================================
# 核心：构建 messages 数组（含摘要压缩）
# ============================================================

def build_messages(session_id: str, user_message: str) -> list:
    """组装发给 LLM 的 messages，长对话自动套摘要"""
    history = get_history(session_id)
    summary = get_summary(session_id)
    msg_count = len(history)

    messages = []
    system_content = "你是一个友好的智能助手，回答简洁清晰。"

    # 如果历史太长，用摘要代替旧消息
    if msg_count >= MAX_HISTORY_MESSAGES and summary:
        system_content = f"你是一个友好的智能助手。以下是对话历史摘要：\n{summary}\n请基于摘要和后续对话回答。"

    messages.append({"role": "system", "content": system_content})

    # 历史太长时只带最近几轮
    if msg_count >= MAX_HISTORY_MESSAGES:
        recent = history[-10:]  # 最近 10 条
        messages.extend(recent)
    else:
        messages.extend(history)

    messages.append({"role": "user", "content": user_message})
    return messages


# ============================================================
# LLM 调用
# ============================================================

def call_llm(messages: list) -> str:
    resp = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": "deepseek-chat", "messages": messages, "temperature": 0.7, "max_tokens": 1000},
        timeout=60,
    )
    if resp.status_code != 200:
        raise Exception(f"API 返回 {resp.status_code}")
    return resp.json()["choices"][0]["message"]["content"]


def call_llm_stream(messages: list):
    resp = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": "deepseek-chat", "messages": messages, "temperature": 0.7, "max_tokens": 1000, "stream": True},
        stream=True, timeout=60,
    )
    for line in resp.iter_lines():
        if line:
            line_str = line.decode("utf-8")
            if line_str.startswith("data: "):
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    delta = json.loads(data_str)["choices"][0]["delta"]
                    if "content" in delta:
                        yield delta["content"]
                except:
                    pass


# ============================================================
# Summary Memory —— 让 LLM 自己总结
# ============================================================

def generate_summary(session_id: str):
    history = get_history(session_id)
    old_summary = get_summary(session_id)

    text = ""
    for h in history:
        text += f"[{h['role']}]: {h['content']}\n"

    prompt = "请用 2-3 句话总结以下对话的关键内容，保留核心信息：\n\n"
    if old_summary:
        prompt = f"之前的摘要：{old_summary}\n\n请基于之前摘要和最新对话，用 2-3 句话更新摘要，保留核心信息：\n\n"

    messages = [
        {"role": "system", "content": "你是一个对话摘要助手，简洁准确。"},
        {"role": "user", "content": prompt + text},
    ]
    summary = call_llm(messages)
    save_summary(session_id, summary, len(history))


# ============================================================
# 接口
# ============================================================

@app.get("/health")
def health():
    try:
        import requests as _r
        _r.get(DEEPSEEK_URL.replace("/chat/completions", ""), timeout=5)
        api_status = "connected"
    except:
        api_status = "unreachable"
    return {"status": "ok", "api": api_status, "sessions": len(get_all_sessions())}


@app.post("/session/create")
def session_create(req: CreateSessionRequest):
    result = create_session(req.session_id, req.name)
    return {"message": "会话创建成功", "session": result}


@app.get("/session/list")
def session_list():
    sessions = get_all_sessions()
    for s in sessions:
        s["message_count"] = get_message_count(s["session_id"])
    return {"total": len(sessions), "sessions": sessions}


@app.delete("/session/{session_id}")
def session_delete(session_id: str):
    delete_session(session_id)
    return {"message": f"会话 {session_id} 已删除"}


@app.get("/session/{session_id}/history")
def session_history(session_id: str):
    history = get_history(session_id)
    summary = get_summary(session_id)
    return {
        "session_id": session_id,
        "message_count": len(history),
        "summary": summary or None,
        "history": history,
    }


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
def chat(req: ChatRequest):
    messages = build_messages(req.session_id, req.message)
    try:
        reply = call_llm(messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {e}")

    add_message(req.session_id, "user", req.message)
    add_message(req.session_id, "assistant", reply)

    # 过长就触发摘要
    if get_message_count(req.session_id) >= MAX_HISTORY_MESSAGES:
        try:
            generate_summary(req.session_id)
        except:
            pass

    return ChatResponse(reply=reply, session_id=req.session_id, message_count=get_message_count(req.session_id))


@app.post("/chat/stream", dependencies=[Depends(verify_api_key)])
async def chat_stream(req: ChatRequest):
    messages = build_messages(req.session_id, req.message)

    async def generate():
        full_reply = ""
        try:
            for token in call_llm_stream(messages):
                full_reply += token
                yield f"data: {json.dumps({'content': token})}\n\n"
            add_message(req.session_id, "user", req.message)
            add_message(req.session_id, "assistant", full_reply)
            if get_message_count(req.session_id) >= MAX_HISTORY_MESSAGES:
                try:
                    generate_summary(req.session_id)
                except:
                    pass
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)
