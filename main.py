import uvicorn
import gspread
import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from gspread_dataframe import get_as_dataframe
from contextlib import asynccontextmanager
import time
import os
import httpx
import json
from pydantic import BaseModel

# --- O'ZGARUVCHILAR ---
GOOGLE_SHEET_NAME = "Dori Bazasi" 
CREDENTIALS_FILE = "credentials.json" 
CACHE_DURATION = 300 
db = pd.DataFrame()
last_fetched_time = 0

# --- Pydantic Modellari ---
class GeminiRequest(BaseModel):
    doriNomi: str

# --- YANGI FUNKSIYA: Krilldan Lotinchaga Tarjimon (Normalizator) ---
# Bu funksiya har qanday matnni lotin alifbosiga o'giradi

CYR_TO_LAT_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'j', 'з': 'z',
    'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '', 'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ў': 'o\'', 'қ': 'q', 'ғ': 'g\'', 'ҳ': 'h',
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo', 'Ж': 'J', 'З': 'Z',
    'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R',
    'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'X', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch',
    'Ъ': '', 'Ы': 'I', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya',
    'Ў': 'O\'', 'Қ': 'Q', 'Ғ': 'G\'', 'Ҳ': 'H'
}

def to_latin(text: str) -> str:
    """ Matnni krilldan lotinga o'g'iruvchi funksiya """
    if not isinstance(text, str):
        return ""
    
    # Lotin harflari bo'lmagan ba'zi belgilarni o'chirish (o', g')
    text = text.replace("o'", "ў").replace("O'", "Ў").replace("g'", "ғ").replace("G'", "Ғ")
    
    result = []
    for char in text:
        result.append(CYR_TO_LAT_MAP.get(char, char))
    
    return "".join(result)

# --- Ma'lumotlarni yuklash funksiyasi (O'ZGARTIRILDI) ---
def load_data_from_sheet():
    global db, last_fetched_time
    print("Google Sheetdan ma'lumotlar yuklanmoqda...")
    try:
        gc = gspread.service_account(filename=CREDENTIALS_FILE)
        sh = gc.open(GOOGLE_SHEET_NAME).sheet1
        
        # Ma'lumotlarni DataFrame'ga o'qish (hammasini satr (string) sifatida)
        db = get_as_dataframe(sh, dtype=str)
        db = db.fillna('') # Bo'sh kataklarni '' bilan to'ldirish
        
        if 'Dori Nomi' in db.columns:
            # YANGI QADAM: Normalizatsiya
            # 'Dori Nomi' ustunini olib, uni lotinchaga o'girib, kichik harfga o'tkazib, 
            # 'Dori Nomi_norm' degan yangi ustunga saqlaymiz.
            db['Dori Nomi_norm'] = db['Dori Nomi'].apply(to_latin).str.lower()
        else:
            print("XATOLIK: 'Dori Nomi' ustuni topilmadi!")
            db = pd.DataFrame() 
            return

        last_fetched_time = time.time()
        print(f"Muvaffaqiyatli yuklandi. Jami {len(db)} ta qator.")
        # print(db[['Dori Nomi', 'Dori Nomi_norm']].head()) # Tekshirish uchun

    except Exception as e:
        print(f"Google Sheetga ulanishda xato: {e}")

# --- Serverning hayot tsikli (Lifespan) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_data_from_sheet()
    yield
    print("Server to'xtamoqda.")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

# --- Asosiy API manzillari ---

@app.get("/")
async def read_root():
    return {"message": "DoriTop API serveri ishlamoqda! (v2.3: Krill/Lotin qidiruvi bilan)"}

# --- Qidiruv Funksiyasi (O'ZGARTIRILDI) ---
@app.get("/search")
async def search_dori(q: str = Query(None, min_length=2)):
    global db, last_fetched_time
    
    # 5 daqiqalik kesh
    if (time.time() - last_fetched_time) > CACHE_DURATION:
        print("Kesh eskirgan. Ma'lumotlar yangilanmoqda...")
        load_data_from_sheet()

    if q is None or len(q) < 2:
        raise HTTPException(status_code=400, detail="Qidiruv so'rovi kamida 2 ta belgidan iborat bo'lishi kerak.")

    # 1-QADAM (O'ZGARDI): Foydalanuvchi so'rovini ham lotincha va kichik harfga o'giramiz
    query_norm = to_latin(q).lower()
    
    if db.empty or 'Dori Nomi_norm' not in db.columns:
        raise HTTPException(status_code=500, detail="Serverda ma'lumotlar bazasi topilmadi yoki xato yuklangan.")

    try:
        # 2-QADAM (O'ZGARDI): Normalizatsiyalangan 'Dori Nomi_norm' ustunidan qidiramiz
        results_df = db[db['Dori Nomi_norm'].str.contains(query_norm, na=False)].copy() 
        
        if results_df.empty:
            return {"results": []}

        # Narx bo'yicha saralash (o'zgarishsiz)
        if 'Narxi' in results_df.columns:
            results_df['Narxi_numeric'] = results_df['Narxi'].str.replace(r'[^\d]', '', regex=True)
            results_df['Narxi_numeric'] = pd.to_numeric(results_df['Narxi_numeric'], errors='coerce')
            results_df = results_df.sort_values(by='Narxi_numeric', ascending=True, na_position='last')
            # Keraksiz ustunlarni olib tashlaymiz
            results_df = results_df.drop(columns=['Dori Nomi_norm', 'Narxi_numeric'], errors='ignore')
        else:
            results_df = results_df.drop(columns=['Dori Nomi_norm'], errors='ignore')
        
        results_json = results_df.to_dict('records')
        return {"results": results_json}
    
    except Exception as e:
        print(f"Qidiruvda xato: {e}")
        raise HTTPException(status_code=500, detail="Qidiruv jarayonida ichki xatolik yuz berdi.")

# --- Gemini Vositachisi (Proxy) (O'zgarishsiz) ---

@app.post("/gemini-info")
async def get_gemini_info(request: GeminiRequest):
    API_KEY = os.getenv("GEMINI_API_KEY")
    if not API_KEY:
        print("XATO: GEMINI_API_KEY server muhitida topilmadi!")
        raise HTTPException(status_code=500, detail="Gemini API kaliti serverda sozlanmagan.")

    dori_nomi = request.doriNomi
    # O'ZGARTIRILDI: Gemini'ga ham lotincha so'rov yuboramiz (ixtiyoriy, lekin yaxshiroq)
    dori_nomi_latin = to_latin(dori_nomi)
    
    GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"

    system_prompt = "Siz O'zbekistondagi farmatsevt yordamchisisiz. Foydalanuvchi so'ragan dori haqida qisqa va tushunarli ma'lumot bering. Barcha javoblar O'zbek tilida bo'lishi kerak. Javob faqat JSON formatida bo'lishi shart."
    user_query = f"\"{dori_nomi_latin}\" dorisi haqida ma'lumot bering." # Lotincha nom yuborildi
    schema = {
        "type": "OBJECT",
        "properties": {
            "qisqa_tavsif": { "type": "STRING", "description": "Dori nima uchun ishlatilishi haqida 2-3 qisqa gap (O'zbek tilida)." },
            "faol_modda": { "type": "STRING", "description": "Dorining asosiy faol moddasi (O'zbek tilida)." },
            "analoglar": {
                "type": "ARRAY",
                "description": "Ushbu doriga o'xshash 3-5 ta eng yaqin analog dori nomlari (O'zbek tilida).",
                "items": { "type": "STRING" }
            }
        },
        "required": ["qisqa_tavsif", "faol_modda", "analoglar"]
    }
    
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_query}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GEMINI_URL, 
                json=payload, 
                headers={"Content-Type": "application/json"},
                timeout=30.0 
            )
        
        if response.status_code == 200:
            gemini_data = response.json()
            try:
                json_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                clean_json = json.loads(json_text)
                return clean_json 
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                print(f"Gemini javobini tahlil qilishda xato: {e}")
                raise HTTPException(status_code=500, detail="Gemini'dan kelgan javobni tahlil qilib bo'lmadi.")
        else:
            print(f"Gemini API xatosi: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Gemini API bilan bog'lanishda xato: {response.text}")

    except httpx.RequestError as e:
        print(f"Gemini'ga ulanishda xato: {e}")
        raise HTTPException(status_code=504, detail=f"Gemini serveriga ulanishda xato: {e}")
    except Exception as e:
        print(f"Noma'lum xato: {e}")
        raise HTTPException(status_code=500, detail=f"Serverda noma'lum xato yuz berdi: {e}")

# --- Serverni ishga tushurish (Lokal) ---
if __name__ == "__main__":
    print("Serverni http://127.0.0.1:8000 manzilda ishga tushirish...")
    uvicorn.run(app, host="127.0.0.1", port=8000)

