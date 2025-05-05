# /home/ubuntu/genia_mcp_server_twilio/main.py
import os
import json
import asyncio
from typing import Dict, Any, AsyncGenerator

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Simplified MCP Message Structures ---
class SimpleTextContent(BaseModel):
    text: str

class SimpleMessage(BaseModel):
    role: str
    content: SimpleTextContent
    metadata: Dict[str, Any] | None = None

# --- FastAPI App ---
app = FastAPI()

# --- Twilio Client Initialization ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
    print("Error: Faltan variables de entorno de Twilio (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER)")
    # Allow startup for now, but requests will fail
    twilio_client = None
else:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        print("Cliente de Twilio inicializado correctamente.")
    except Exception as e:
        print(f"Error al inicializar cliente de Twilio: {e}")
        twilio_client = None

# --- MCP Endpoint Logic ---
async def process_twilio_request(message: SimpleMessage) -> AsyncGenerator[str, None]:
    """Processes the incoming MCP message and interacts with Twilio."""
    capability = message.metadata.get("capability")
    params = message.metadata.get("params", {})
    user_id = message.metadata.get("user_id", "unknown_user") # Get user_id if passed

    if not twilio_client:
        error_content = SimpleTextContent(text=json.dumps({"message": "Error interno: Cliente de Twilio no inicializado."}))
        error_msg = SimpleMessage(role="error", content=error_content)
        yield json.dumps(error_msg.dict())
        return

    if capability == "send_whatsapp_message":
        to_number = params.get("to")
        body = params.get("body")

        if not to_number or not body:
            error_content = SimpleTextContent(text=json.dumps({"message": "Parámetros 'to' y 'body' son requeridos para send_whatsapp_message"}))
            error_msg = SimpleMessage(role="error", content=error_content)
            yield json.dumps(error_msg.dict())
            return

        try:
            # Ensure 'to' number has the correct prefix
            if not to_number.startswith("whatsapp:"):
                to_number = f"whatsapp:{to_number}"
            
            # Ensure 'from' number has the correct prefix
            from_number = TWILIO_WHATSAPP_NUMBER
            if not from_number.startswith("whatsapp:"):
                 from_number = f"whatsapp:{from_number}"

            message_response = twilio_client.messages.create(
                from_=from_number,
                body=body,
                to=to_number
            )
            
            result_data = {"message_sid": message_response.sid, "status": message_response.status}
            response_content = SimpleTextContent(text=json.dumps(result_data))
            response_msg = SimpleMessage(role="assistant", content=response_content)
            yield json.dumps(response_msg.dict())

        except TwilioRestException as e:
            error_content = SimpleTextContent(text=json.dumps({"message": f"Error de Twilio: {e.msg}", "details": {"twilio_code": e.code, "status": e.status}}))
            error_msg = SimpleMessage(role="error", content=error_content)
            yield json.dumps(error_msg.dict())
        except Exception as e:
            error_content = SimpleTextContent(text=json.dumps({"message": f"Error inesperado al enviar mensaje: {str(e)}"}))
            error_msg = SimpleMessage(role="error", content=error_content)
            yield json.dumps(error_msg.dict())

    else:
        error_content = SimpleTextContent(text=json.dumps({"message": f"Capacidad no soportada: {capability}"}))
        error_msg = SimpleMessage(role="error", content=error_content)
        yield json.dumps(error_msg.dict())

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """MCP endpoint to handle requests via SSE."""
    try:
        data = await request.json()
        incoming_message = SimpleMessage(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request format: {e}")

    return EventSourceResponse(process_twilio_request(incoming_message))

@app.get("/")
async def root():
    return {"message": "Servidor MCP de Twilio para GENIA está activo."}

# --- Run Server (for local testing) ---
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor MCP de Twilio en http://localhost:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003)

