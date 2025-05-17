# /home/ubuntu/genia_mcp_server_twilio/main.py
import os
import json
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional
import logging

from fastapi import FastAPI, Request, HTTPException, Form, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables (primarily for local development)
load_dotenv()

# --- Simplified MCP Message Structures ---
class SimpleTextContent(BaseModel):
    text: str

class SimpleMessage(BaseModel):
    role: str
    content: SimpleTextContent
    metadata: Dict[str, Any] | None = None

# --- FastAPI App ---
app = FastAPI(
    title="GENIA Simplified MCP Server - Twilio",
    description="Servidor simplificado para interactuar con Twilio (WhatsApp) vía SSE.",
)

# --- Twilio Client Initialization ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
BACKEND_WEBHOOK_URL = os.getenv("BACKEND_WEBHOOK_URL", "https://genia-backendmpc.onrender.com/webhook/twilio")

twilio_client = None
if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
    logger.warning("Faltan variables de entorno de Twilio (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER). Las solicitudes a Twilio fallarán.")
else:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logger.info("Cliente de Twilio inicializado correctamente.")
    except Exception as e:
        logger.error(f"Error al inicializar cliente de Twilio: {e}")

# --- MCP Endpoint Logic ---
async def process_twilio_request(message: SimpleMessage) -> AsyncGenerator[str, None]:
    """Processes the incoming MCP message and interacts with Twilio."""
    logger.info(f"Servidor Twilio Simplificado recibió: {message.model_dump_json()}")
    capability = message.metadata.get("capability") if message.metadata else None
    params = message.metadata.get("params", {}) if message.metadata else {}
    user_id = message.metadata.get("user_id", "unknown_user") if message.metadata else "unknown_user" # Get user_id if passed

    if not twilio_client:
        error_content = SimpleTextContent(text=json.dumps({"message": "Error interno: Cliente de Twilio no inicializado (faltan credenciales).".strip()}))
        error_msg = SimpleMessage(role="error", content=error_content)
        yield json.dumps(error_msg.dict())
        yield {"event": "end", "data": "Stream ended due to error"}
        return

    try:
        if capability == "send_whatsapp_message":
            to_number = params.get("to")
            body = params.get("body")

            if not to_number or not body:
                raise ValueError("Parámetros 'to' y 'body' son requeridos para send_whatsapp_message")

            logger.info(f"Ejecutando capacidad: send_whatsapp_message a {to_number}")
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
            logger.info(f"Mensaje enviado a Twilio: SID {message_response.sid}, Status {message_response.status}")

        else:
            raise ValueError(f"Capacidad no soportada: {capability}")

    except TwilioRestException as e:
        logger.error(f"Error de Twilio al procesar capacidad 	'{capability}	': {e.msg} (Code: {e.code}, Status: {e.status})", exc_info=True)
        error_content = SimpleTextContent(text=json.dumps({"message": f"Error de Twilio: {e.msg}", "details": {"twilio_code": e.code, "status": e.status}}))
        error_msg = SimpleMessage(role="error", content=error_content)
        yield json.dumps(error_msg.dict())
    except Exception as e:
        logger.exception(f"Error inesperado al procesar capacidad 	'{capability}	': {e}")
        error_content = SimpleTextContent(text=json.dumps({"message": f"Error inesperado al procesar la solicitud ({capability}): {str(e)}"}))
        error_msg = SimpleMessage(role="error", content=error_content)
        yield json.dumps(error_msg.dict())
    finally:
        # Signal end
        yield {"event": "end", "data": "Stream ended"}
        logger.info("Stream SSE finalizado.")

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """MCP endpoint to handle requests via SSE."""
    try:
        data = await request.json()
        incoming_message = SimpleMessage(**data)
    except Exception as e:
        logger.error(f"Error al parsear request JSON: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid request format: {e}")

    return EventSourceResponse(process_twilio_request(incoming_message))

# --- Webhook Endpoints for Twilio ---
@app.post("/webhook/twilio")
@app.post("/webhook/twilio/{path:path}")
async def twilio_webhook_catchall(
    request: Request,
    path: Optional[str] = None,
    Body: Optional[str] = Form(None),
    From: Optional[str] = Form(None),
    To: Optional[str] = Form(None),
    ProfileName: Optional[str] = Form(None)
):
    """
    Webhook catch-all para recibir mensajes de Twilio desde cualquier ruta que comience con /webhook/twilio.
    Este endpoint reenvía los datos al backend principal para su procesamiento.
    """
    logger.info(f"Webhook recibido de Twilio en ruta: /webhook/twilio/{path if path else ''}")
    logger.info(f"Detalles: From: {From}, To: {To}, ProfileName: {ProfileName}")
    
    if not Body or not From:
        logger.error("Mensaje recibido sin cuerpo o remitente")
        raise HTTPException(status_code=400, detail="Mensaje recibido sin cuerpo o remitente")
    
    try:
        # Procesar el mensaje directamente aquí
        logger.info(f"Mensaje de WhatsApp recibido: {Body}")
        
        # Devolver una respuesta vacía a Twilio para evitar mensajes duplicados
        return {}
    
    except Exception as e:
        logger.exception(f"Error al procesar mensaje de WhatsApp: {e}")
        # En caso de error, intentar enviar un mensaje de error al usuario
        try:
            if From:
                formatted_sender = From if From.startswith("whatsapp:") else f"whatsapp:{From}"
                if twilio_client:
                    from_number = TWILIO_WHATSAPP_NUMBER
                    if not from_number.startswith("whatsapp:"):
                        from_number = f"whatsapp:{from_number}"
                    
                    twilio_client.messages.create(
                        from_=from_number,
                        body="Lo siento, ocurrió un error al procesar tu solicitud. Por favor, intenta de nuevo más tarde.",
                        to=formatted_sender
                    )
        except Exception as send_err:
            logger.error(f"No se pudo enviar mensaje de error a {From}: {send_err}")
        
        # Devolver una respuesta vacía a Twilio
        return {}

@app.get("/")
async def root():
    return {"message": "Servidor MCP de Twilio para GENIA está activo. Endpoint SSE (POST) en /mcp, Webhook en /webhook/twilio"}

# --- Run Server (for Render) ---
if __name__ == "__main__":
    import uvicorn
    # Render provides the PORT environment variable
    port = int(os.getenv("PORT", 8003)) # Default to 8003 if PORT not set
    logger.info(f"Iniciando servidor MCP de Twilio en http://0.0.0.0:{port}")
    # Listen on 0.0.0.0 as required by Render
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False) # Disable reload for production
