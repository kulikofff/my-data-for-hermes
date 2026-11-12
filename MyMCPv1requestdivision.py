import os
import httpx
import traceback
import json
import asyncio
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

# Настройка портов для разных моделей (поменяйте 13306 на нужный порт переводчика, если он отличается)
GENERAL_COMPLETION_URL = "http://127.0.0.1:13305/v1/chat/completions"
TRANSLATE_COMPLETION_URL = "http://127.0.0.1:13306/v1/chat/completions"

def make_openai_response(text_content: str):
    return {
        "id": "chatcmpl-local-router",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "local-router",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text_content
                },
                "logprobs": None,
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": len(text_content) // 4, 
            "completion_tokens": len(text_content) // 4, 
            "total_tokens": len(text_content) // 2
        }
    }

@app.post("/chat/completions")
@app.post("/v1/chat/completions")
@app.post("/mcp/chat/completions")
@app.post("/mcp/v1/chat/completions")
async def handle_chat_completions(request: Request):
    try:
        body = await request.json()
        messages = body.get("messages", [])
        
        user_prompt = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_prompt = msg.get("content", "")
                break
        
        print(f"\n🤖 Перехвачен запрос от Hermes. Последняя фраза: '{user_prompt}'")
        user_prompt_lower = user_prompt.lower()

        translate_keywords = ["переведи", "перевод", "перевести", "translate", "translation", "на английский", "на русский"]
        
        if any(word in user_prompt_lower for word in translate_keywords):
            target_url = TRANSLATE_COMPLETION_URL
            print(f"🌐 Маршрутизация: Запрос на ПЕРЕВОД отправлен на {target_url}")
        else:
            target_url = GENERAL_COMPLETION_URL
            print(f"📝 Маршрутизация: ОБЩИЙ запрос отправлен на {target_url}")

        llama_payload = {
            "messages": messages, 
            "temperature": 0.2, 
            "max_tokens": 2048,  
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False}
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(target_url, json=llama_payload, timeout=300.0)
                print(f"📡 Статус ответа от сервера ({target_url}): {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    
                    try:
                        text_out = result["choices"][0]["message"]["content"].strip()
                    except (KeyError, IndexError, TypeError):
                        text_out = result.get("content", "").strip()
                    
                    print(f"✅ Успешный ответ. Сырой текст: ===\n{text_out}\n===")
                    
                    is_streaming = body.get("stream", True)
                    
                    if is_streaming:
                        async def openai_stream_generator(text: str):
                            chunks = text.split(" ")
                            for i, chunk in enumerate(chunks):
                                current_text = chunk + (" " if i < len(chunks) - 1 else "")
                                chunk_data = {
                                    "id": "chatcmpl-local-router",
                                    "object": "chat.completion.chunk",
                                    "created": 1700000000,
                                    "model": "local-router",
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {"content": current_text},
                                            "finish_reason": None
                                        }
                                    ]
                                }
                                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                                await asyncio.sleep(0.01)
                            
                            final_chunk = {
                                "id": "chatcmpl-local-router",
                                "object": "chat.completion.chunk",
                                "created": 1700000000,
                                "model": "local-router",
                                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                            }
                            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
                            yield "data: [DONE]\n\n"

                        return StreamingResponse(openai_stream_generator(text_out), media_type="text/event-stream")
                    else:
                        return JSONResponse(content=make_openai_response(text_out))
                
                print(f"❌ Сервер вернул ошибку {response.status_code}")
                return JSONResponse(content=make_openai_response(f"❌ Ошибка бэкенда (код {response.status_code})"))
            except Exception as e:
                print(f"💥 ИСКЛЮЧЕНИЕ ПРИ HTTP ЗАПРОСЕ: {str(e)}")
                print(traceback.format_exc())
                return JSONResponse(content=make_openai_response(f"❌ Ошибка связи с моделью: {str(e)}"))

    except Exception as e:
        print(f"💥 КРИТИЧЕСКАЯ ОШИБКА В РОУТЕРЕ: {str(e)}")
        return JSONResponse(
            content=make_openai_response(f"❌ Внутренняя ошибка прокси-сервера: {str(e)}"),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@app.get("/models")
@app.get("/v1/models")
@app.get("/mcp/models")
@app.get("/mcp/v1/models")
async def mock_models():
    return JSONResponse(content={
        "object": "list",
        "data": [{"id": "local-router", "object": "model", "owned_by": "user"}]
    }, status_code=status.HTTP_200_OK)

@app.post("/mcp/api/show")
async def mock_api_show():
    return JSONResponse(content={
        "modelfile": "# Mock Modelfile",
        "parameters": "stop",
        "template": "{{ .Prompt }}"
    }, status_code=status.HTTP_200_OK)

if __name__ == "__main__":
    import uvicorn
    print("🚀 Финальный OpenAI/MCP-совместимый роутер запущен на http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)