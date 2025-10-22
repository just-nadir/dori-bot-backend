import uvicorn
import gspread
import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from gspread_dataframe import get_as_dataframe
from contextlib import asynccontextmanager
import time

# --- O'ZGARUVCHILAR ---
GOOGLE_SHEET_NAME = "Dori Bazasi" 
CREDENTIALS_FILE = "credentials.json" 
CACHE_DURATION = 300 
# --- --- --- --- --- ---

db = pd.DataFrame()
last_fetched_time = 0

def load_data_from_sheet():
    global db, last_fetched_time
    print("Google Sheetdan ma'lumotlar yuklanmoqda...")
    try:
        gc = gspread.service_account(filename=CREDENTIALS_FILE)
        sh = gc.open(GOOGLE_SHEET_NAME) 
        worksheet = sh.get_worksheet(0) 
        
        db = get_as_dataframe(worksheet, dtype=str)
        db = db.fillna('') 
        
        if 'Dori Nomi' in db.columns:
            db['Dori Nomi_lower'] = db['Dori Nomi'].str.lower()
        else:
            print("Xatolik: 'Dori Nomi' ustuni topilmadi!")
            db = pd.DataFrame() 
            return

        last_fetched_time = time.time()
        print(f"Muvaffaqiyatli yuklandi. Jami {len(db)} ta qator.")

    except Exception as e:
        print(f"Google Sheetga ulanishda xato: {e}")

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

@app.get("/")
async def read_root():
    return {"message": "DoriTop API serveri ishlamoqda! (v2: Saralash bilan - Diagnostika rejimi)"}

# --- O'ZGARTIRILGAN FUNKSIYA (DIAGNOSTIKA PRINTLARI BILAN) ---
@app.get("/search")
async def search_dori(q: str = Query(None, min_length=2)):
    """
    Dorilarni qidiradi va narx bo'yicha saralaydi. (Diagnostika rejimi)
    """
    global db, last_fetched_time

    if (time.time() - last_fetched_time) > CACHE_DURATION:
        print("Kesh eskirgan. Ma'lumotlar yangilanmoqda...")
        load_data_from_sheet()

    if q is None or len(q) < 2:
        raise HTTPException(status_code=400, detail="Qidiruv so'rovi kamida 2 ta belgidan iborat bo'lishi kerak.")

    query = q.lower()
    
    if db.empty or 'Dori Nomi_lower' not in db.columns:
        raise HTTPException(status_code=500, detail="Serverda ma'lumotlar bazasi topilmadi yoki xato yuklangan.")

    try:
        # 1. QIDIRUV
        results_df = db[db['Dori Nomi_lower'].str.contains(query, na=False)].copy() 
        
        if results_df.empty:
            return {"results": []}

        print(f"--- DIAGNOSTIKA: QIDIRUV: {query} ---")
        print("Topilgan natijalar (saralashdan oldin):")
        print(results_df[['Dori Nomi', 'Narxi']])

        # 2. TOZALASH VA O'GIRISH
        if 'Narxi' in results_df.columns:
            print("Saralash boshlandi. 'Narxi' ustuni topildi.")
            
            # .str.replace() - bu faqat string ma'lumotlar ustida ishlash uchun ishonchliroq
            results_df['Narxi_numeric'] = results_df['Narxi'].str.replace(r'[^\d]', '', regex=True)
            print("'Narxi' ustuni raqam bo'lmagan belgilardan tozalandi (Narxi_numeric):")
            print(results_df['Narxi_numeric'])
            
            results_df['Narxi_numeric'] = pd.to_numeric(results_df['Narxi_numeric'], errors='coerce')
            print("'Narxi_numeric' ustuni raqam formatiga o'girildi (NaN - xato yoki bo'sh):")
            print(results_df['Narxi_numeric'])

            # 3. SARALASH
            results_df = results_df.sort_values(by='Narxi_numeric', ascending=True, na_position='last')
            print("Narx bo'yicha saralandi:")
            print(results_df[['Dori Nomi', 'Narxi', 'Narxi_numeric']])
            
            # 4. YORDAMCHI USTUNLARNI O'CHIRISH
            results_df = results_df.drop(columns=['Dori Nomi_lower', 'Narxi_numeric'])
        
        else:
            print("DIQQAT: 'Narxi' ustuni topilmadi. Saralash amalga oshirilmadi.")
            results_df = results_df.drop(columns=['Dori Nomi_lower'])

        # 5. NATIJA
        results_json = results_df.to_dict('records')
        
        print("--- Qidiruv yakunlandi ---")
        return {"results": results_json}
    
    except Exception as e:
        print(f"Qidiruvda KATTA XATO: {e}")
        raise HTTPException(status_code=500, detail="Qidiruv jarayonida ichki xatolik yuz berdi.")

if __name__ == "__main__":
    print("Serverni http://127.0.0.1:8000 manzilda ishga tushurish...")
    uvicorn.run(app, host="127.0.0.1", port=8000)

