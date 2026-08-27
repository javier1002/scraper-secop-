from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
import base64
import json
import asyncio
import traceback

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TARGET_URL = "https://community.secop.gov.co/Public/Common/GoogleReCaptcha/Index?previousUrl=https%3a%2f%2fcommunity.secop.gov.co%2fPublic%2fTendering%2fContractNoticeManagement%2fIndex%3fcurrentLanguage%3des-CO%26Page%3dlogin%26Country%3dCO%26SkinName%3dCCE"

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1280,1024")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options)
    
    # Coordenadas globales para hacer tracking del puntero
    current_x = 0
    current_y = 0

    def capture_screenshot():
        return base64.b64encode(driver.get_screenshot_as_png()).decode('utf-8')

    def execute_click(target_x, target_y):
        nonlocal current_x, current_y
        actions = ActionChains(driver)
        
        # Calcular la diferencia desde la última posición conocida
        offset_x = target_x - current_x
        offset_y = target_y - current_y
        
        # Mover y hacer clic
        actions.move_by_offset(offset_x, offset_y).click().perform()
        
        # Actualizar la posición del cursor
        current_x = target_x
        current_y = target_y

    try:
        # 1. Navegar a SECOP II
        await asyncio.to_thread(driver.get, TARGET_URL)
        await asyncio.sleep(2)
        
        # Enviar captura inicial
        img_b64 = await asyncio.to_thread(capture_screenshot)
        await websocket.send_text(json.dumps({"type": "image", "data": f"data:image/png;base64,{img_b64}"}))

        # 2. Bucle de eventos bidireccional
        while True:
            data_str = await websocket.receive_text()
            message = json.loads(data_str)

            if message.get("action") == "click":
                x = int(message["x"])
                y = int(message["y"])

                try:
                    await asyncio.to_thread(execute_click, x, y)
                except Exception as click_err:
                    print(f"Error al ejecutar clic: {click_err}")

                await asyncio.sleep(1.2) # Pausa para renderizado de reCAPTCHA

                # Responder con nueva pantalla
                updated_img = await asyncio.to_thread(capture_screenshot)
                await websocket.send_text(json.dumps({"type": "image", "data": f"data:image/png;base64,{updated_img}"}))

    except WebSocketDisconnect:
        print("Cliente desconectado de forma limpia")
    except Exception as e:
        print("Error en WebSocket:")
        traceback.print_exc()
    finally:
        driver.quit()