import os
import json
import boto3
import streamlit as st
import pandas as pd
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta
import pathlib

# ─────────────────────────────────────────────────────────────
# CONFIG — โหลดจาก Streamlit secrets
# ─────────────────────────────────────────────────────────────
def get_secret(key: str, section: str = None) -> str:
    """Get secret from Streamlit secrets (supports nested structure)"""
    try:
        if section and section in st.secrets and key in st.secrets[section]:
            return st.secrets[section][key]
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, "")

CONFIG = {
    "AWS_ACCESS_KEY_ID": get_secret("AWS_ACCESS_KEY_ID", "aws"),
    "AWS_SECRET_ACCESS_KEY": get_secret("AWS_SECRET_ACCESS_KEY", "aws"),
    "AWS_REGION": get_secret("AWS_REGION", "aws") or "us-east-1",
    "OVERRUN_BUCKET": get_secret("OVERRUN_BUCKET", "s3") or "overrun",
    "SUMMARY_BUCKET": get_secret("SUMMARY_BUCKET", "s3") or "report-staging1",
    "BEDROCK_MODEL_ID": get_secret("BEDROCK_MODEL_ID", "bedrock"),
}

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Finance Dashboard Report", layout="wide")
st.title("📊 Report Generator")

# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────
def s3_client():
    return boto3.client(
        "s3",
        region_name=CONFIG["AWS_REGION"],
        aws_access_key_id=CONFIG["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=CONFIG["AWS_SECRET_ACCESS_KEY"],
    )

def list_alert_files(bucket: str) -> List[Dict[str, Any]]:
    """List all alert JSON files from S3 bucket"""
    s3 = s3_client()
    files_info = []
    
    try:
        resp = s3.list_objects_v2(Bucket=bucket, MaxKeys=1000)
        
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            # รูปแบบ: 20251014MG1_3_alerts.json
            if key.lower().endswith("_alerts.json"):
                try:
                    filename = key.split("/")[-1]
                    # แยกวันที่จากชื่อไฟล์ (8 หลักแรก: YYYYMMDD)
                    date_str = filename[:8]
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    
                    files_info.append({
                        "key": key,
                        "date": file_date,
                        "last_modified": obj["LastModified"],
                        "size": obj["Size"]
                    })
                except (IndexError, ValueError) as e:
                    continue
        
        # เรียงตามวันที่ใหม่ไปเก่า
        files_info.sort(key=lambda x: x["date"], reverse=True)
        
    except Exception as e:
        st.error(f"❌ ไม่สามารถดึงรายการไฟล์จาก S3: {e}")
    
    return files_info

def fetch_alert_data(bucket: str, key: str) -> Optional[Dict[str, Any]]:
    """Fetch and parse alert JSON from S3"""
    try:
        s3 = s3_client()
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        data = json.loads(body)
        return data
    except Exception as e:
        st.error(f"❌ ไม่สามารถอ่านไฟล์ {key}: {e}")
        return None

def build_llm_prompt(alerts: List[Dict[str, Any]]) -> str:
    """สร้าง prompt สำหรับ Bedrock AI"""
    
    # แยก RED alerts
    red_alerts = [a for a in alerts if a.get("status", "").upper() == "RED"]
    green_alerts = [a for a in alerts if a.get("status", "").upper() == "GREEN"]
    
    total_budget = sum(a.get("budget", 0) for a in alerts)
    total_actual = sum(a.get("actual", 0) for a in alerts)
    
    # สร้างตาราง RED alerts
    table_rows = []
    for alert in red_alerts:
        cost_code = alert.get("cost_code", "N/A")
        costname = alert.get("costname", "")
        budget = alert.get("budget", 0)
        actual = alert.get("actual", 0)
        overrun = actual - budget
        overrun_pct = (overrun / budget * 100) if budget > 0 else 0
        
        # กำหนดระดับความรุนแรง
        if overrun_pct > 200:
            risk_level = "วิกฤติสุด"
        elif overrun_pct > 100:
            risk_level = "รุนแรงมาก"
        elif overrun_pct > 50:
            risk_level = "รุนแรง"
        elif overrun_pct > 20:
            risk_level = "ปานกลาง"
        else:
            risk_level = "เล็กน้อย"
        
        table_rows.append(
            f"| {cost_code} | {costname} | {budget:,.0f} | {actual:,.0f} | {overrun:,.0f} | {overrun_pct:.1f}% | {risk_level} |"
        )
    
    table_header = """
| Cost Code | ชื่อหมวดงาน | งบประมาณ (บาท) | ค่าใช้จ่ายจริง (บาท) | Overrun (บาท) | Overrun % | ระดับความรุนแรง |
|-----------|-------------|----------------|---------------------|---------------|-----------|------------------|"""
    
    cost_code_table = table_header + "\n" + "\n".join(table_rows) if table_rows else "ไม่พบข้อมูล Overrun"
    
    # ดึง report_date จาก alert แรก
    report_date = alerts[0].get("report_date", "N/A") if alerts else "N/A"
    project_name = alerts[0].get("project_name", "N/A") if alerts else "N/A"
    
    return f"""
คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์งบประมาณโครงการ  
หน้าที่ของคุณคือจัดทำรายงานสรุปสำหรับผู้บริหารในรูปแบบที่อ่านง่ายและมีโครงสร้างชัดเจน

**ข้อกำหนดสำคัญ:**
- ให้แสดง "ตาราง Cost Code" ก่อนเริ่มรายงาน โดยใช้รูปแบบ Markdown เดิม **ห้ามแก้ไขหรือแปลงรูปแบบตาราง**
- ให้เขียนรายงานใน **ภาษาไทยเท่านั้น**
- ใช้น้ำเสียงเป็นทางการ เชิงวิเคราะห์ แต่กระชับและเข้าใจง่าย
- วิเคราะห์ว่า cost code ไหนบ้างที่ overrun (status = RED) และ overrun มาจากช่วงเดือนใด

---

**ข้อมูลโครงการ**
- โครงการ: {project_name}
- วันที่รายงาน: {report_date}
- จำนวน Cost Codes ทั้งหมด: {len(alerts)} รายการ
- จำนวน Cost Codes ที่ Overrun (RED): {len(red_alerts)} รายการ
- จำนวน Cost Codes ที่ปกติ (GREEN): {len(green_alerts)} รายการ
- งบประมาณรวม: {total_budget:,.0f} บาท
- ค่าใช้จ่ายจริงรวม: {total_actual:,.0f} บาท

---

**ตารางข้อมูล Cost Codes ที่ Overrun (Status = RED)**
```markdown
{cost_code_table}
```

กรุณาจัดทำรายงานโดยใช้รูปแบบนี้เท่านั้น:

📊 **สรุปสถานการณ์โครงการ**
วิเคราะห์ภาพรวมของสถานการณ์งบประมาณและผลกระทบต่อโครงการ

⚠️ **Cost Codes ที่ต้องติดตามเร่งด่วน**
วิเคราะห์ Cost Codes ที่มีปัญหารุนแรง แบ่งตามระดับความรุนแรง
**สำคัญ:** วิเคราะห์ว่า overrun เกิดขึ้นในช่วงเดือนใด (ดูจาก report_date: {report_date})

🧐 **การวิเคราะห์สาเหตุ**
วิเคราะห์ปัจจัยที่อาจก่อให้เกิด Overrun

💡 **แนวทางแก้ไขและการจัดการ**
เสนอแนะแนวทางจัดการปัญหาที่ชัดเจนและนำไปปฏิบัติได้จริง

🛡️ **ระบบป้องกันและติดตาม**
เสนอแนะแนวทางป้องกันการเกิด Overrun ซ้ำในอนาคต
""".strip()

def call_bedrock(prompt: str) -> str:
    """เรียก Bedrock AI เพื่อวิเคราะห์ข้อมูล"""
    try:
        client = boto3.client(
            "bedrock-runtime",
            region_name=CONFIG["AWS_REGION"],
            aws_access_key_id=CONFIG["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=CONFIG["AWS_SECRET_ACCESS_KEY"],
        )
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
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
        return "\n".join(texts).strip() or "(LLM ไม่ได้ส่งข้อความ)"
    except Exception as e:
        return f"❌ เกิดข้อผิดพลาดจาก Bedrock: {e}"

def save_report_to_s3(report_content: str, report_date: str, project_name: str = "MG1") -> bool:
    """บันทึก report ลง S3 bucket"""
    try:
        s3 = s3_client()
        
        # สร้างชื่อไฟล์: YYYYMMDD_projectname_report_TIMESTAMP.json
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_date.replace('-', '')}_{project_name}_report_{timestamp}.json"
        
        # สร้าง JSON structure
        report_data = {
            "report_date": report_date,
            "project_name": project_name,
            "generated_at": datetime.now().isoformat(),
            "summary": report_content
        }
        
        # Upload to S3
        s3.put_object(
            Bucket=CONFIG["SUMMARY_BUCKET"],
            Key=filename,
            Body=json.dumps(report_data, ensure_ascii=False, indent=2),
            ContentType="application/json"
        )
        
        return True
    except Exception as e:
        st.error(f"❌ ไม่สามารถบันทึก report ลง S3: {e}")
        return False

# ─────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────
go = st.button("🚀 Generate Report", type="primary", use_container_width=True)

if go:
    with st.spinner('⏳ กำลังประมวลผลข้อมูล...'):
        # ดึงรายการไฟล์จาก S3
        files = list_alert_files(CONFIG["OVERRUN_BUCKET"])
        
        if not files:
            st.warning("⚠️ ไม่พบไฟล์ alerts ใน S3 bucket")
        else:
            # เอาไฟล์ล่าสุด
            latest_file = files[0]
            st.info(f"📅 ใช้ข้อมูลจากไฟล์: {latest_file['key']} (วันที่: {latest_file['date'].strftime('%d/%m/%Y')})")
            
            # ดึงข้อมูล
            data = fetch_alert_data(CONFIG["OVERRUN_BUCKET"], latest_file['key'])
            
            if data and "alerts" in data:
                alerts = data["alerts"]
                st.success(f"✅ พบข้อมูล {len(alerts)} รายการ")
                
                # นับ RED vs GREEN
                red_count = sum(1 for a in alerts if a.get("status", "").upper() == "RED")
                green_count = sum(1 for a in alerts if a.get("status", "").upper() == "GREEN")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("รายการทั้งหมด", len(alerts))
                with col2:
                    st.metric("Overrun (RED)", red_count, delta=f"{red_count/len(alerts)*100:.1f}%")
                with col3:
                    st.metric("ปกติ (GREEN)", green_count)
                
                # แสดงตารางเฉพาะ field ที่ต้องการ พร้อม emoji status
                df = pd.DataFrame(alerts)
                
                # ฟังก์ชันสำหรับแปลง status เป็น emoji
                def status_emoji(s):
                    s = str(s).upper()
                    if s == "RED":
                        return "🔴 RED"
                    elif s == "GREEN":
                        return "🟢 GREEN"
                    else:
                        return s
                
                # เลือกเฉพาะคอลัมน์ที่ต้องการ (ใช้ reindex เพื่อป้องกัน KeyError)
                selected_columns = ["plan_code", "cost_code", "costname", "budget", "actual", "progress_per", "eac", "status"]
                
                # สร้าง DataFrame ใหม่ โดยใช้ reindex เพื่อจัดการคอลัมน์ที่หายไป
                df_display = df.reindex(columns=selected_columns, fill_value="")
                
                # เปลี่ยนชื่อคอลัมน์
                df_display = df_display.rename(columns={
                    "plan_code": "Plan Code",
                    "cost_code": "Cost Code",
                    "costname": "Cost Name",
                    "budget": "Budget",
                    "actual": "Actual",
                    "progress_per": "Progress Percent",
                    "eac": "EAC",
                    "status": "Status"
                })
                
                # แปลง status เป็น emoji
                df_display["Status"] = df_display["Status"].apply(status_emoji)
                
                st.dataframe(df_display, use_container_width=True)
                
                # สร้าง prompt และเรียก LLM
                if red_count > 0:
                    st.subheader("🧾 Executive Summary (AI Analysis)")
                    st.info("🤖 กำลังวิเคราะห์ข้อมูลด้วย AI...")
                    
                    prompt = build_llm_prompt(alerts)
                    summary = call_bedrock(prompt)
                    st.markdown(summary)
                    
                    # บันทึก report ลง S3
                    report_date = alerts[0].get("report_date", datetime.now().strftime("%Y-%m-%d")) if alerts else datetime.now().strftime("%Y-%m-%d")
                    project_name = alerts[0].get("plan_code", "MG1") if alerts else "MG1"
                    
                    with st.spinner("💾 กำลังบันทึก report ลง S3..."):
                        if save_report_to_s3(summary, report_date, project_name):
                            st.success(f"✅ บันทึก report สำเร็จ → S3 bucket: {CONFIG['SUMMARY_BUCKET']}")
                        else:
                            st.warning("⚠️ ไม่สามารถบันทึก report ได้")
                else:
                    st.success("✅ ไม่พบรายการ Overrun (Status = RED)")
            else:
                st.error("❌ ไม่สามารถอ่านข้อมูล alerts จากไฟล์")
else:
    st.caption("กดปุ่ม **Generate Report** เพื่อเริ่มวิเคราะห์ข้อมูล")