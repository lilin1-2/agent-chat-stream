# Agent 流式对话服务

## 简介

基于 DeepSeek API 的多轮对话服务，支持 Session 隔离、SQLite 持久化、SSE 流式输出和 Summary Memory。

## 核心功能

- **Session 隔离** —— 按用户维度创建/切换/删除会话，多用户并发不串
- **SQLite 持久化** —— 对话历史存数据库，服务重启自动恢复上下文
- **Summary Memory** —— 对话过长时 LLM 自动摘要压缩，替代简单截断
- **SSE 流式输出** —— 手动解析 chunk 实现打字机效果

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/session/create` | 创建会话 |
| GET | `/session/list` | 列出所有会话 |
| DELETE | `/session/{id}` | 删除会话 |
| GET | `/session/{id}/history` | 查看历史 |
| POST | `/chat` | 非流式对话 |
| POST | `/chat/stream` | SSE 流式对话 |

## 快速开始

```bash
pip install -r requirements.txt
cp config_example.py config.py
# 编辑 config.py 填入 API Key
python app.py
```

## 测试

```bash
# 创建会话
curl -X POST http://localhost:8002/session/create \
  -H "Content-Type: application/json" \
  -d '{"session_id":"user_001"}'

# 对话
curl -X POST http://localhost:8002/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"user_001","message":"你好，我叫小明"}'

# 查看历史
curl http://localhost:8002/session/user_001/history
```

## 技术栈

Python · FastAPI · DeepSeek API · SQLite · SSE · Summary Memory
