import uvicorn  # Serverni ishga tushurish uchun
import gspread  # Google Sheets bilan ishlash uchun
import pandas as pd  # Ma'lumotlarni oson qayta ishlash uchun
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware  # Turli manzillardan so'rovga ruxsat berish
from gspread_dataframe import get_as_dataframe  # Google Sheetni DataFramega o'tkazish
from contextlib import asynccontextmanager
import time

# --- O'ZGARUVCHILAR ---
# Google Sheet faylingizning aniq nomini yozing
GOOGLE_SHEET_NAME = "Dori Bazasi" 
# Service account faylingiz nomi
CREDENTIALS_FILE = "credentials.json" 
# Qancha vaqt ma'lumotni keshda saqlash (sekundda). 300 sekund = 5 daqiqa
CACHE_DURATION = 300 
# --- --- --- --- --- ---

# Global o'zgaruvchilar (kesh uchun)
db = pd.DataFrame() # Ma'lumotlar bazasi (Pandas DataFrame)
last_fetched_time = 0 # Oxirgi yuklab olingan vaqt

def load_data_from_sheet():
    """
    Google Sheetdan ma'lumotlarni o'qiydi va `db` global o'zgaruvchisiga yuklaydi.
    """
    global db, last_fetched_time
    print("Google Sheetdan ma'lumotlar yuklanmoqda...")
    try:
        # Google bilan bog'lanish
        gc = gspread.service_account(filename=CREDENTIALS_FILE)
        # Faylni nomi bo'yicha ochish
        sh = gc.open(GOOGLE_SHEET_NAME) 
        # Birinchi listni (worksheet) olish
        worksheet = sh.get_worksheet(0) 
        
        # Ma'lumotlarni Pandas DataFramega o'qib olish
        # 'dtype=str' - barcha ustunlarni matn sifatida o'qish (xatolikni oldini oladi)
        db = get_as_dataframe(worksheet, dtype=str)
        
        # NaN (bo'sh) kataklarni bo'sh string '' ga o'zgartirish
        db = db.fillna('') 
        
        # Qidiruv oson bo'lishi uchun 'Dori Nomi' ustunini kichik harflarga o'tkazish
        if 'Dori Nomi' in db.columns:
            db['Dori Nomi_lower'] = db['Dori Nomi'].str.lower()
        else:
            print("Xatolik: 'Dori Nomi' ustuni topilmadi!")
            db = pd.DataFrame() # Xatolik bo'lsa bazani bo'shatish
            return

        last_fetched_time = time.time() # Oxirgi yuklanish vaqtini saqlash
        print(f"Muvaffaqiyatli yuklandi. Jami {len(db)} ta qator.")

    except Exception as e:
        print(f"Google Sheetga ulanishda xato: {e}")
        # Agar xato bo'lsa, eski ma'lumotlar bilan ishlashda davom etadi

# FastAPI ilovasi ishga tushganda bir marta ishlaydigan funksiya
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ilova ishga tushganda...
    load_data_from_sheet() # Birinchi marta ma'lumotlarni yuklab olamiz
    yield
    # Ilova to'xtaganda... (bizga hozircha kerak emas)
    print("Server to'xtamoqda.")


# --- API ILovasini Yaratish ---
app = FastAPI(lifespan=lifespan)

# CORS sozlamalari (Juda muhim!)
# Bu bizning Mini App (boshqa domenda) APIga so'rov yuborishi uchun kerak.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Hamma manzillarga ruxsat (keyinchalik xavfsizlik uchun faqat Vercel manzilini qo'yamiz)
    allow_credentials=True,
    allow_methods=["*"],  # Hamma metodlarga (GET, POST) ruxsat
    allow_headers=["*"],
)

# --- API Endpoints (Manzillari) ---

@app.get("/")
async def read_root():
    """
    Asosiy manzil. API ishlayotganini tekshirish uchun.
    """
    return {"message": "DoriTop API serveri ishlamoqda!"}

@app.get("/search")
async def search_dori(q: str = Query(None, min_length=2)):
    """
    Dorilarni qidirish uchun asosiy manzil.
    Namuna: /search?q=nospa
    """
    global db, last_fetched_time

    # Kesh eskirganligini tekshirish (5 daqiqadan ko'p o'tgan bo'lsa)
    if (time.time() - last_fetched_time) > CACHE_DURATION:
        print("Kesh eskirgan. Ma'lumotlar yangilanmoqda...")
        load_data_from_sheet()

    if q is None or len(q) < 2:
        raise HTTPException(status_code=400, detail="Qidiruv so'rovi kamida 2 ta belgidan iborat bo'lishi kerak.")

    # Qidiruv so'rovini kichik harfga o'tkazish
    query = q.lower()
    
    if db.empty or 'Dori Nomi_lower' not in db.columns:
        raise HTTPException(status_code=500, detail="Serverda ma'lumotlar bazasi topilmadi yoki xato yuklangan.")

    try:
        # Ma'lumotlar bazasidan (Pandas) qidirish
        # 'Dori Nomi_lower' ustunida 'query' so'zi qatnashgan qatorlarni topish
        results_df = db[db['Dori Nomi_lower'].str.contains(query, na=False)]
        
        # 'Dori Nomi_lower' yordamchi ustunini natijadan olib tashlash
        results_df = results_df.drop(columns=['Dori Nomi_lower'])

        # DataFrame'ni JSON formatiga o'tkazish (ro'yxat ko'rinishida)
        results_json = results_df.to_dict('records')
        
        return {"results": results_json}
    
    except Exception as e:
        print(f"Qidiruvda xato: {e}")
        raise HTTPException(status_code=500, detail="Qidiruv jarayonida ichki xatolik yuz berdi.")

# Serverni ishga tushirish
if __name__ == "__main__":
    # Bu qism `python main.py` buyrug'i bilan ishga tushurish uchun
    print("Serverni http://127.0.0.1:8000 manzilda ishga tushurish...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
