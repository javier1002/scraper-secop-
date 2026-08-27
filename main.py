from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import base64
import json
import asyncio
import io
import pandas as pd
from PIL import Image

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
    is_solved = False

    def fast_screenshot_jpg():
        png_data = driver.get_screenshot_as_png()
        img = Image.open(io.BytesIO(png_data))
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=55)
        return base64.b64encode(output.getvalue()).decode('utf-8')

    def cdp_click(x, y):
        driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

    def check_if_captcha_solved():
        # Comprobar que ya NO estemos en la página de GoogleReCaptcha/Index
        current_url = driver.current_url
        if "GoogleReCaptcha" not in current_url:
            return True
        return False

    def scrape_secop_data():
        scraped_data = []
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.gridRow, tr.gridRowAlt, table tbody tr")
        
        for row in rows[:20]:
            text = row.text.strip()
            if text:
                scraped_data.append({"Proceso": text})
                
        if not scraped_data:
            elements = driver.find_elements(By.TAG_NAME, "a")
            for elem in elements[:20]:
                title = elem.text.strip()
                if title:
                    scraped_data.append({"Elemento": title, "Link": elem.get_attribute("href")})

        return scraped_data

    # Tarea background: refresca el canvas a 5 FPS constantemente
    async def auto_stream_video():
        nonlocal is_solved
        while not is_solved:
            try:
                jpg_b64 = await asyncio.to_thread(fast_screenshot_jpg)
                await websocket.send_text(json.dumps({"type": "image", "data": f"data:image/jpeg;base64,{jpg_b64}"}))
                
                # Verificar si ya superó el CAPTCHA
                if await asyncio.to_thread(check_if_captcha_solved):
                    is_solved = True
                    break

                await asyncio.sleep(0.2)
            except Exception:
                break

    try:
        await asyncio.to_thread(driver.get, TARGET_URL)
        await asyncio.sleep(1.5)

        stream_task = asyncio.create_task(auto_stream_video())

        while not is_solved:
            data_str = await websocket.receive_text()
            message = json.loads(data_str)

            if message.get("action") == "click":
                x = int(message["x"])
                y = int(message["y"])
                await asyncio.to_thread(cdp_click, x, y)

        stream_task.cancel()

        # Notificar resolución real
        await websocket.send_text(json.dumps({"type": "status", "message": "¡CAPTCHA Superado! Extrayendo datos de SECOP II..."}))
        await asyncio.sleep(4)

        results = await asyncio.to_thread(scrape_secop_data)
        await websocket.send_text(json.dumps({
            "type": "download", 
            "filename": "secop_data.json", 
            "payload": results
        }))

    except WebSocketDisconnect:
        print("Cliente desconectado")
    finally:
        driver.quit()