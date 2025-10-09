# report_app_standalone.py
# Streamlit Finance Dashboard — ALL-IN-ONE CONFIG (RDS + S3 Overrun + Bedrock)
# - ไม่ต้องใช้ไฟล์ config เพิ่ม: กำหนดค่าได้ในบล็อก CONFIG ด้านล่าง
# - ดึง “ข้อมูลหลัก” จาก RDS → ตาราง finance_data ตาม report_date
# - อ่าน Overrun JSON ตรงจาก S3 (OVERRUN_BUCKET) — เติม/คำนวณ actual/budget/overrun_pct ให้อัตโนมัติ
# - เรียก Bedrock สรุป 5 ส่วนพร้อม emoji
# - ปุ่ม Generate เลือก 30 วัน / 3 เดือน / กำหนดเอง

import os
import json
import boto3
import psycopg2
import streamlit as st
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta

# ─────────────────────────────────────────────────────────────
# CONFIG — โหลดจาก Streamlit secrets, ENV หรือไฟล์ config/config.json
# - For Streamlit sharing / Streamlit Cloud: put secrets in .streamlit/secrets.toml
# - Local fallback: set environment variables or create config/config.json (example included)
# - This keeps secrets out of source control.
# ─────────────────────────────────────────────────────────────

import pathlib

def _load_local_config() -> dict:
    cfg_path = pathlib.Path(__file__).parent / "config" / "config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# Priority: Streamlit secrets -> environment variables -> config/config.json
local_cfg = _load_local_config()

CONFIG = {
    "DB_HOST": st.secrets.get("DB_HOST") if "DB_HOST" in st.secrets else os.environ.get("DB_HOST") or local_cfg.get("DB_HOST"),
    "DB_NAME": st.secrets.get("DB_NAME") if "DB_NAME" in st.secrets else os.environ.get("DB_NAME") or local_cfg.get("DB_NAME"),
    "DB_USER": st.secrets.get("DB_USER") if "DB_USER" in st.secrets else os.environ.get("DB_USER") or local_cfg.get("DB_USER"),
    "DB_PASSWORD": st.secrets.get("DB_PASSWORD") if "DB_PASSWORD" in st.secrets else os.environ.get("DB_PASSWORD") or local_cfg.get("DB_PASSWORD"),
    "DB_PORT": int(st.secrets.get("DB_PORT")) if "DB_PORT" in st.secrets else int(os.environ.get("DB_PORT", local_cfg.get("DB_PORT", 5432))),
    "DB_SSLMODE": st.secrets.get("DB_SSLMODE") if "DB_SSLMODE" in st.secrets else os.environ.get("DB_SSLMODE") or local_cfg.get("DB_SSLMODE", "require"),
    "DB_CONNECT_TIMEOUT": int(st.secrets.get("DB_CONNECT_TIMEOUT")) if "DB_CONNECT_TIMEOUT" in st.secrets else int(os.environ.get("DB_CONNECT_TIMEOUT", local_cfg.get("DB_CONNECT_TIMEOUT", 20))),
    "TABLE_FINANCE": st.secrets.get("TABLE_FINANCE") if "TABLE_FINANCE" in st.secrets else os.environ.get("TABLE_FINANCE") or local_cfg.get("TABLE_FINANCE", "FINANCE_DATA"),

    "AWS_ACCESS_KEY_ID": st.secrets.get("AWS_ACCESS_KEY_ID") if "AWS_ACCESS_KEY_ID" in st.secrets else os.environ.get("AWS_ACCESS_KEY_ID") or local_cfg.get("AWS_ACCESS_KEY_ID"),
    "AWS_SECRET_ACCESS_KEY": st.secrets.get("AWS_SECRET_ACCESS_KEY") if "AWS_SECRET_ACCESS_KEY" in st.secrets else os.environ.get("AWS_SECRET_ACCESS_KEY") or local_cfg.get("AWS_SECRET_ACCESS_KEY"),
    "AWS_REGION": st.secrets.get("AWS_REGION") if "AWS_REGION" in st.secrets else os.environ.get("AWS_REGION") or local_cfg.get("AWS_REGION", "us-east-1"),

    "OVERRUN_BUCKET": st.secrets.get("OVERRUN_BUCKET") if "OVERRUN_BUCKET" in st.secrets else os.environ.get("OVERRUN_BUCKET") or local_cfg.get("OVERRUN_BUCKET", "overrun"),
    "SUMMARY_BUCKET": st.secrets.get("SUMMARY_BUCKET") if "SUMMARY_BUCKET" in st.secrets else os.environ.get("SUMMARY_BUCKET") or local_cfg.get("SUMMARY_BUCKET"),

    "BEDROCK_MODEL_ID": st.secrets.get("BEDROCK_MODEL_ID") if "BEDROCK_MODEL_ID" in st.secrets else os.environ.get("BEDROCK_MODEL_ID") or local_cfg.get("BEDROCK_MODEL_ID"),

    "OVERRUN_LIST_MAX_FILES": int(st.secrets.get("OVERRUN_LIST_MAX_FILES")) if "OVERRUN_LIST_MAX_FILES" in st.secrets else int(os.environ.get("OVERRUN_LIST_MAX_FILES", local_cfg.get("OVERRUN_LIST_MAX_FILES", 2000))),
}

# Optional: surface a warning if obvious secrets are missing when running locally
if not CONFIG.get("DB_HOST") or not CONFIG.get("DB_PASSWORD"):
    st.warning("ยังไม่ได้ตั้งค่า credentials: ใส่ค่าใน .streamlit/secrets.toml หรือ environment variables หรือ config/config.json")


import pathlib
import json

def _load_local_config() -> dict:
    cfg_path = pathlib.Path(__file__).parent / "config" / "config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# Priority: Streamlit secrets -> environment variables -> config/config.json
local_cfg = _load_local_config()

CONFIG = {
    "DB_HOST": st.secrets.get("DB_HOST") if "DB_HOST" in st.secrets else os.environ.get("DB_HOST") or local_cfg.get("DB_HOST"),
    "DB_NAME": st.secrets.get("DB_NAME") if "DB_NAME" in st.secrets else os.environ.get("DB_NAME") or local_cfg.get("DB_NAME"),
    "DB_USER": st.secrets.get("DB_USER") if "DB_USER" in st.secrets else os.environ.get("DB_USER") or local_cfg.get("DB_USER"),
    "DB_PASSWORD": st.secrets.get("DB_PASSWORD") if "DB_PASSWORD" in st.secrets else os.environ.get("DB_PASSWORD") or local_cfg.get("DB_PASSWORD"),
    "DB_PORT": int(st.secrets.get("DB_PORT")) if "DB_PORT" in st.secrets else int(os.environ.get("DB_PORT", local_cfg.get("DB_PORT", 5432))),
    "DB_SSLMODE": st.secrets.get("DB_SSLMODE") if "DB_SSLMODE" in st.secrets else os.environ.get("DB_SSLMODE") or local_cfg.get("DB_SSLMODE", "require"),
    "DB_CONNECT_TIMEOUT": int(st.secrets.get("DB_CONNECT_TIMEOUT")) if "DB_CONNECT_TIMEOUT" in st.secrets else int(os.environ.get("DB_CONNECT_TIMEOUT", local_cfg.get("DB_CONNECT_TIMEOUT", 20))),
    "TABLE_FINANCE": st.secrets.get("TABLE_FINANCE") if "TABLE_FINANCE" in st.secrets else os.environ.get("TABLE_FINANCE") or local_cfg.get("TABLE_FINANCE", "FINANCE_DATA"),

    "AWS_ACCESS_KEY_ID": st.secrets.get("AWS_ACCESS_KEY_ID") if "AWS_ACCESS_KEY_ID" in st.secrets else os.environ.get("AWS_ACCESS_KEY_ID") or local_cfg.get("AWS_ACCESS_KEY_ID"),
    "AWS_SECRET_ACCESS_KEY": st.secrets.get("AWS_SECRET_ACCESS_KEY") if "AWS_SECRET_ACCESS_KEY" in st.secrets else os.environ.get("AWS_SECRET_ACCESS_KEY") or local_cfg.get("AWS_SECRET_ACCESS_KEY"),
    "AWS_REGION": st.secrets.get("AWS_REGION") if "AWS_REGION" in st.secrets else os.environ.get("AWS_REGION") or local_cfg.get("AWS_REGION", "us-east-1"),

    "OVERRUN_BUCKET": st.secrets.get("OVERRUN_BUCKET") if "OVERRUN_BUCKET" in st.secrets else os.environ.get("OVERRUN_BUCKET") or local_cfg.get("OVERRUN_BUCKET", "overrun"),
    "SUMMARY_BUCKET": st.secrets.get("SUMMARY_BUCKET") if "SUMMARY_BUCKET" in st.secrets else os.environ.get("SUMMARY_BUCKET") or local_cfg.get("SUMMARY_BUCKET"),

    "BEDROCK_MODEL_ID": st.secrets.get("BEDROCK_MODEL_ID") if "BEDROCK_MODEL_ID" in st.secrets else os.environ.get("BEDROCK_MODEL_ID") or local_cfg.get("BEDROCK_MODEL_ID"),

    "OVERRUN_LIST_MAX_FILES": int(st.secrets.get("OVERRUN_LIST_MAX_FILES")) if "OVERRUN_LIST_MAX_FILES" in st.secrets else int(os.environ.get("OVERRUN_LIST_MAX_FILES", local_cfg.get("OVERRUN_LIST_MAX_FILES", 2000))),
}

# Optional: surface a warning if obvious secrets are missing when running locally
if not CONFIG.get("DB_HOST") or not CONFIG.get("DB_PASSWORD"):
    st.warning("ยังไม่ได้ตั้งค่า credentials: ใส่ค่าใน .streamlit/secrets.toml หรือ environment variables หรือ config/config.json")

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG — ต้องเป็นคำสั่งแรกใน Streamlit
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Finance Dashboard Report (Standalone)", layout="wide")
st.title("Report Generator")

# ─────────────────────────────────────────────────────────────
# Helpers — DB / S3 / util
# ─────────────────────────────────────────────────────────────
def db_connect():
    dsn = (
        f"host={CONFIG['DB_HOST']} "
        f"dbname={CONFIG['DB_NAME']} "
        f"user={CONFIG['DB_USER']} "
        f"password={CONFIG['DB_PASSWORD']} "
        f"port={CONFIG['DB_PORT']} "
        f"sslmode={CONFIG['DB_SSLMODE']} "
        f"connect_timeout={CONFIG['DB_CONNECT_TIMEOUT']}"
    )
    return psycopg2.connect(dsn)

def s3_client():
    return boto3.client(
        "s3",
        region_name=CONFIG["AWS_REGION"],
        aws_access_key_id=CONFIG["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=CONFIG["AWS_SECRET_ACCESS_KEY"],
    )

def safety_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None: return default
        if isinstance(x, (int, float)): return float(x)
        if isinstance(x, str) and x.strip() == "": return default
        return float(x)
    except Exception:
        return default

# ─────────────────────────────────────────────────────────────
# 1) ดึงข้อมูลหลักจาก RDS: finance_data (ตาม report_date)
# ─────────────────────────────────────────────────────────────
def query_finance_data(start_date: date, end_date: date, costcode_filter: Optional[str] = None) -> pd.DataFrame:
    sql = f"""
    SELECT
      plan_code,
      costcode,
      ym,
      report_date,
      updated_at,
      acamt_accumulated,
      amount_ym_acc,
      taskname,
      planname,
      amount,
      amount_ym,
      amount_acc_today,
      progress_ym,
      progress_ym_acc,
      acamt
    FROM {CONFIG['TABLE_FINANCE']}
    WHERE report_date >= %s AND report_date <= %s
    """
    params = [start_date, end_date]
    if costcode_filter:
        sql += " AND costcode = %s"
        params.append(costcode_filter)

    # เพิ่ม ORDER BY เพื่อดูข้อมูลล่าสุดก่อน
    sql += " ORDER BY report_date DESC, updated_at DESC"

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                
        return pd.DataFrame(rows, columns=cols)
    except Exception as e:
        st.error(f"❌ ดึงข้อมูลจาก RDS ล้มเหลว: {e}")
        return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
# 2) อ่าน Overrun JSON จาก S3 + Normalize + Get Latest
# ─────────────────────────────────────────────────────────────
def _get_latest_alerts(all_overruns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """กรองข้อมูล Overrun ที่ซ้ำซ้อนกัน โดยเก็บเฉพาะรายการที่มี updated_at ล่าสุด"""
    latest_items: Dict[Tuple[str, str], Dict[str, Any]] = {}
    
    for item in all_overruns:
        # สร้างคีย์สำหรับระบุความซ้ำซ้อน (Cost Code + Plan Code คือ Unique ID)
        cost_code = item.get("cost_code") or item.get("costcode")
        plan_code = item.get("plan_code")
        unique_key = (cost_code, plan_code)
        
        if not all(unique_key):  # ถ้า cost_code หรือ plan_code เป็น None
            continue
            
        # แปลง updated_at เป็น datetime object
        updated_at_str = item.get("updated_at")
        if not updated_at_str:
            continue
            
        try:
            current_updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
            
        # ตรวจสอบว่ารายการนี้ใหม่กว่ารายการที่เก็บไว้หรือไม่
        if unique_key not in latest_items or \
           current_updated_at > latest_items[unique_key]["datetime_obj"]:
            latest_items[unique_key] = {
                "datetime_obj": current_updated_at,
                "data": item
            }

    # ดึงเฉพาะข้อมูล (data) ออกมาเป็น list
    return [d["data"] for d in latest_items.values()]
def list_all_json_keys(bucket: str, max_keys: int = 2000) -> List[Dict[str, Any]]:
    s3 = s3_client()
    files_info: List[Dict[str, Any]] = []
    
    try:
        kwargs = {
            "Bucket": bucket,
            "MaxKeys": max_keys
        }
        resp = s3.list_objects_v2(**kwargs)
        
        # เก็บข้อมูลไฟล์ JSON ที่มีรูปแบบ YYYYMMDDTHHMMSSz_XXX_alerts.json
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            # ตรวจสอบว่าเป็นไฟล์ alerts.json
            if key.lower().endswith("_alerts.json"):
                try:
                    # แยกส่วนของวันที่เวลาออกมา (20251007T182646Z)
                    timestamp_str = key.split("/")[-1].split("_")[0]
                    # แปลงเป็น datetime object
                    file_datetime = datetime.strptime(timestamp_str, "%Y%m%dT%H%M%SZ")
                    files_info.append({
                        "key": key,
                        "last_modified": obj["LastModified"],
                        "file_datetime": file_datetime,
                        "size": obj["Size"]
                    })
                except (IndexError, ValueError):
                    # ข้ามไฟล์ที่ชื่อไม่ตรงรูปแบบ
                    continue
        
        # เรียงตาม file_datetime จากใหม่ไปเก่า (ใช้เวลาในชื่อไฟล์แทน last_modified)
        files_info.sort(key=lambda x: x["file_datetime"], reverse=True)
        
    except Exception as e:
        st.error(f"ไม่สามารถดึงรายการไฟล์จาก S3 ได้: {e}")
        files_info = []
        
    return files_info

def fetch_json(bucket: str, key: str) -> Optional[Dict[str, Any]]:
    s3 = s3_client()
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if isinstance(data, dict):
        data["__s3_key"] = key
    return data


def normalize_overrun_payload(src: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    ตรวจสอบ status RED และดึง costcode
    """
    # ตรวจสอบ status ก่อน
    status = src.get("status", "").upper()
    if status != "RED":
        return None
        
    # ดึงเฉพาะ costcode
    costcode = src.get("costcode") or src.get("cost_code")
    if not costcode:
        return None
        
    return {"costcode": costcode}

    # pct
    overrun_pct = src.get("overrun_pct")
    remaining_budget_pct = src.get("remaining_budget_pct")
    if overrun_pct is None or remaining_budget_pct is None:
        if budget > 0:
            overrun_amt = max(0.0, actual - budget)
            overrun_pct = (overrun_amt / budget) * 100.0
            remaining_budget_pct = max(0.0, (budget - actual) / budget * 100.0)
        else:
            overrun_pct = 0.0
            remaining_budget_pct = 0.0
    dst["overrun_pct"] = safety_float(overrun_pct, 0.0)
    dst["remaining_budget_pct"] = safety_float(remaining_budget_pct, 0.0)
    return dst

def load_overrun_from_s3(bucket: str, start_date: date, end_date: date, max_files: int = 2000) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
    files_info = list_all_json_keys(bucket, max_keys=max_files)
    out: List[Dict[str, Any]] = []
    latest_file_info = None
    red_alerts_count = 0
    overrun_costcodes: List[str] = []  # เก็บ costcode ที่มี status RED
    
    if files_info:
        # เก็บข้อมูลไฟล์ล่าสุดไว้แยก
        latest_file_info = files_info[0]
        # ดึงข้อมูลจากไฟล์ล่าสุด
        latest_data = fetch_json(bucket, latest_file_info['key'])
        if latest_data and isinstance(latest_data, dict):
            # ดึง costcode ที่มี status RED จากข้อมูลล่าสุด
            alerts = latest_data.get('alerts', [])
            if isinstance(alerts, list):
                for alert in alerts:
                    if isinstance(alert, dict):
                        status = alert.get('status', '').upper()
                        costcode = alert.get('cost_code') or alert.get('costcode')
                        if status == 'RED' and costcode:
                            if costcode not in overrun_costcodes:
                                overrun_costcodes.append(costcode)
                                red_alerts_count += 1
            
            normalized = normalize_overrun_payload(latest_data)
            if normalized:
                out.append(normalized)
    
    return out, latest_file_info, overrun_costcodes

# ─────────────────────────────────────────────────────────────
# 3) สร้าง Prompt และเรียก Bedrock
# ─────────────────────────────────────────────────────────────
def build_llm_prompt(fin_df: pd.DataFrame, overrun_costcodes: List[str],
                     start_d: date, end_d: date) -> str:
    # กรองข้อมูลจาก RDS เฉพาะ costcode ที่มี status RED จาก S3
    overrun_df = fin_df[fin_df['costcode'].isin(overrun_costcodes)] if not fin_df.empty else pd.DataFrame()
    
    # รวบรวมข้อมูลสำหรับ prompt
    total_rows = len(fin_df)
    total_overrun = len(overrun_costcodes)
    overrun_details = []
    total_budget = 0
    total_actual = 0
    
    # สร้างตารางข้อมูล Cost Codes ที่ Overrun
    table_rows = []
    for costcode in overrun_costcodes:
        code_data = overrun_df[overrun_df['costcode'] == costcode]
        if not code_data.empty:
            latest_data = code_data.iloc[-1]  # ข้อมูลล่าสุด
            
            # คำนวณ % overrun จากค่าจริง
            actual = latest_data['acamt_accumulated']
            budget = latest_data['amount']
            
            # ตรวจสอบและแปลงค่า
            if pd.notna(actual):
                actual = float(actual)
            else:
                actual = 0.0
                
            if pd.notna(budget):
                budget = float(budget)
            else:
                budget = 0.0
            
            overrun_pct = ((actual - budget) / budget * 100) if budget > 0 else 0
            
            total_budget += budget
            total_actual += actual
            
            # กำหนดระดับความรุนแรง
            if overrun_pct > 7000:
                risk_level = "วิกฤติสุด"
            elif overrun_pct > 4000:
                risk_level = "รุนแรงมาก"
            elif overrun_pct > 1000:
                risk_level = "รุนแรง"
            elif overrun_pct > 500:
                risk_level = "ปานกลาง"
            else:
                risk_level = "เล็กน้อย"
            
            # เพิ่มแถวในตาราง (ไม่แสดงเปอร์เซ็นต์)
            table_rows.append(f"| {costcode} | {budget:,.0f} | {actual:,.0f} | {risk_level} |")
    
    # สร้างตารางในรูปแบบ Markdown (ไม่มีคอลัมน์ Overrun %)
    table_header = """
| Cost Code | งบประมาณ (บาท) | ค่าใช้จ่ายจริง (บาท) | ระดับความรุนแรง |
|-----------|----------------|---------------------|------------------|"""
    
    cost_code_table = table_header + "\n" + "\n".join(table_rows) if table_rows else "ไม่พบข้อมูลรายละเอียด"
    total_overrun_pct = ((total_actual - total_budget) / total_budget * 100) if total_budget > 0 else 0

    return f"""
คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์งบประมาณโครงการ  
หน้าที่ของคุณคือจัดทำรายงานสรุปสำหรับผู้บริหารในรูปแบบที่อ่านง่ายและมีโครงสร้างชัดเจน

**ข้อกำหนดสำคัญ:**
- ให้แสดง "ตาราง Cost Code" ก่อนเริ่มรายงาน โดยใช้รูปแบบ Markdown เดิม **ห้ามแก้ไขหรือแปลงรูปแบบตาราง**
- ให้ครอบตารางด้วย code block ```markdown เพื่อคงรูปแบบ
- ให้เขียนรายงานใน **ภาษาไทยเท่านั้น**
- ใช้น้ำเสียงเป็นทางการ เชิงวิเคราะห์ แต่กระชับและเข้าใจง่าย
- ห้ามแปลงตัวเลขในตารางเป็นข้อความบรรยาย
- ให้เรียงลำดับเนื้อหาตามโครงสร้างด้านล่างเท่านั้น

---

**ข้อมูลโครงการ**
- ช่วงเวลารายงาน: {start_d:%d %b %Y} - {end_d:%d %b %Y}
- จำนวนรายการทั้งหมด: {total_rows:,} รายการ
- จำนวน Cost Codes ที่ Overrun: {total_overrun} รายการ
- งบประมาณรวม: {total_budget:,.0f} บาท
- ค่าใช้จ่ายจริงรวม: {total_actual:,.0f} บาท
- Overrun รวม: {total_overrun_pct:.2f}%

---

**ตารางข้อมูล Cost Codes ที่ Overrun**
```markdown
{cost_code_table}
```

กรุณาจัดทำรายงานโดยใช้รูปแบบนี้เท่านั้น:

📊 **สรุปสถานการณ์โครงการ**

วิเคราะห์ภาพรวมของสถานการณ์งบประมาณและผลกระทบต่อโครงการ
เน้น insight ทางธุรกิจและแนวโน้มโดยไม่ต้องแสดงตัวเลขซ้ำจากตาราง

⚠️ **Cost Codes ที่ต้องติดตามเร่งด่วน**

วิเคราะห์ Cost Codes ที่มีปัญหารุนแรง แบ่งตามระดับความรุนแรง (จากคอลัมน์ "ระดับความรุนแรง")
อ้างอิงจากตารางเท่านั้น ไม่ต้องเขียนตัวเลขใหม่

🧐 **การวิเคราะห์สาเหตุ**

วิเคราะห์ปัจจัยสำคัญที่อาจก่อให้เกิด Overrun เช่น การวางแผน, วัสดุ, ค่าแรง, การควบคุมงบ

💡 **แนวทางแก้ไขและการจัดการ**

เสนอแนะแนวทางจัดการปัญหาที่ชัดเจนและนำไปปฏิบัติได้จริง
เน้นข้อเสนอแบบ actionable

🛡️ **ระบบป้องกันและติดตาม**

เสนอแนะแนวทางป้องกันการเกิด Overrun ซ้ำในอนาคต
อาจรวมถึงระบบติดตาม, dashboard, หรือ early warning system
""".strip()

def call_bedrock(prompt: str) -> str:
    try:
        client = boto3.client(
            "bedrock-runtime",
            region_name=CONFIG["AWS_REGION"],
            aws_access_key_id=CONFIG["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=CONFIG["AWS_SECRET_ACCESS_KEY"],
        )
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
        resp = client.invoke_model(
            modelId=CONFIG["BEDROCK_MODEL_ID"],
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        payload = json.loads(resp["body"].read())
        parts = payload.get("content", [])
        texts = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                texts.append(p.get("text", ""))
        out = "\n".join(texts).strip()
        return out or "(LLM ไม่ได้ส่งข้อความ)"
    except Exception as e:
        return f"(ข้าม Bedrock: {e})"

# ─────────────────────────────────────────────────────────────
# 4) UI — เลือกช่วงเวลา + ปุ่ม Generate
# ─────────────────────────────────────────────────────────────
# UI — ปุ่ม Generate Report (3 เดือนย้อนหลัง)
# ─────────────────────────────────────────────────────────────

# กำหนดช่วงเวลา 3 เดือนย้อนหลัง
today = date.today()
start_d = today - timedelta(days=90)
end_d = today

go = st.button("🚀 Generate Report", type="primary", use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 5) RUN — เมื่อกด Generate
# ─────────────────────────────────────────────────────────────
if go:
    with st.spinner('⏳ กำลังประมวลผลข้อมูล...'):
        st.info(f"📅 ช่วงเวลารายงาน: {start_d.strftime('%d/%m/%Y')} - {end_d.strftime('%d/%m/%Y')}")

        # 5.1 RDS
        fin_df = query_finance_data(start_d, end_d, None)
    
    
    if not fin_df.empty:
        # แสดงข้อมูลทุกคอลัมน์ที่เกี่ยวกับ actual และ budget
        actual_budget_cols = [
            "plan_code", "costcode", "ym", "report_date",
            "acamt_accumulated", "amount_ym_acc", "amount_acc_today", 
            "acamt", "amount", "amount_ym", 
            "progress_ym", "progress_ym_acc"
        ]
        
        
        
        
        # แสดงตัวอย่างข้อมูลล่าสุด

    # 5.2 S3 Overrun (จาก overrun/overrun/batch/)
    overrun_items, latest_file, overrun_costcodes = load_overrun_from_s3(
        CONFIG["OVERRUN_BUCKET"], 
        start_d, 
        end_d,
        max_files=CONFIG["OVERRUN_LIST_MAX_FILES"]
    )
    
    # กรองเอาเฉพาะรายการล่าสุดของแต่ละ cost code + plan code
    latest_overruns = _get_latest_alerts(overrun_items)
    
    # 5.3 LLM Summary
    st.subheader("🧾 Executive Summary ")
    
    # ถ้ามี overrun_costcodes ให้สร้าง prompt และเรียก LLM
    if overrun_costcodes:
        prompt = build_llm_prompt(fin_df, overrun_costcodes, start_d, end_d)
        st.info("🤖 กำลังวิเคราะห์ข้อมูลด้วย AI...")
        
        summary = call_bedrock(prompt)
        st.write(summary)
    else:
        st.success("✅ ไม่พบรายการ Overrun (Status = RED) ในช่วงเวลาที่เลือก")

else:
    st.caption("ตั้งค่าช่วงเวลา แล้วกดปุ่ม **Generate Report** เพื่อเริ่มทำงาน")

