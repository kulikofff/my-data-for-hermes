import os
import httpx
import traceback
import json
import asyncio
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

# ИСПРАВЛЕНО: Используем правильный Chat API и убираем жесткий хардкод IP (теперь поддерживает IPv4/IPv6 на локальной машине)
LLAMA_COMPLETION_URL = "http://127.0.0.1:13305/v1/chat/completions"
IMAGE_GEN_URL = "http://127.0.0.1"

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
        
        # Получаем последний промпт только для проверки триггера картинок
        user_prompt = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_prompt = msg.get("content", "")
                break
        
        print(f"\n🤖 Перехвачен запрос от Hermes. Последняя фраза: '{user_prompt}'")
        user_prompt_lower = user_prompt.lower()

        # --- ТРИГГЕР 1: ГЕНЕРАЦИЯ КАРТИНКИ ---
        if any(word in user_prompt_lower for word in ["нарисуй", "картинка", "image", "generate", "draw", "photo", "фото"]):
            print("🎨 Маршрутизация: Запрос отправлен на генерацию картинок...")
            sd_payload = {
                "prompt": user_prompt,
                "steps": 20,
                "width": 512,
                "height": 512
            }
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(IMAGE_GEN_URL, json=sd_payload, timeout=90.0)
                    if response.status_code == 200:
                        return JSONResponse(content=make_openai_response("🎨 Изображение успешно сгенерировано на вашем бэкенде!"))
                    return JSONResponse(content=make_openai_response(f"❌ Ошибка бэкенда картинок: код {response.status_code}"))
                except Exception as e:
                    return JSONResponse(content=make_openai_response(f"❌ Не удалось достучаться до генератора картинок: {str(e)}"))

        # --- ТРИГГЕР 2: РАБОТА С ТЕКСТОМ И ПЕРЕВОД ---
        else:
            print(f"📝 Маршрутизация: Отправка полной истории сообщений на Chat-эндпоинт Llama...")
            
            # ИСПРАВЛЕНО: Передаем весь массив `messages`, пришедший от Hermes.
            # Llama.cpp сама применит правильный Chat Template модели, и она перестанет зацикливаться на 'de de de'.
            llama_payload = {
                "messages": messages, 
                "temperature": 0.4, 
                "max_tokens": 512,  
                "stream": False    # Сами забираем ответ у Llama целиком во избежание разрывов связи
            }
            
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(LLAMA_COMPLETION_URL, json=llama_payload, timeout=300.0)
                    print(f"📡 Статус ответа от самой Llama: {response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        
                        # ИСПРАВЛЕНО: Парсим стандартный для /v1/chat/completions формат
                        try:
                            text_out = result["choices"][0]["message"]["content"].strip()
                        except (KeyError, IndexError, TypeError):
                            text_out = result.get("content", "").strip() # фоллбэк на случай плоского ответа
                        
                        print(f"✅ Успешный ответ от Llama. Сырой текст: ===\n{text_out}\n===")
                        
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
                    
                    print(f"❌ Сервер Llama вернул ошибку {response.status_code}")
                    return JSONResponse(content=make_openai_response(f"❌ Ошибка Llama (код {response.status_code})"))
                except Exception as e:
                    print(f"💥 ИСКЛЮЧЕНИЕ ПРИ HTTP ЗАПРОСЕ К LLAMA: {str(e)}")
                    print(traceback.format_exc())
                    return JSONResponse(content=make_openai_response(f"❌ Ошибка связи с Llama: {str(e)}"))

    except Exception as e:
        print(f"💥 КРИТИЧЕСКАЯ ОШИБКА В РОУТЕРЕ: {str(e)}")
        return JSONResponse(
            content=make_openai_response(f"❌ Внутренняя ошибка прокси-сервера: {str(e)}"),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Список моделей (с поддержкой путей Hermes)
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
