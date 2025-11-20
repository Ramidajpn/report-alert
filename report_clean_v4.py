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

def fetch_graph_data(bucket: str, date_str: str) -> Optional[List[Dict[str, Any]]]:
    """Fetch graph data from S3 (format: YYYYMMDD_graph.json)"""
    try:
        s3 = s3_client()
        key = f"overrun/batch/{date_str}_graph.json"
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        data = json.loads(body)
        return data if isinstance(data, list) else []
    except Exception as e:
        return None

def build_llm_prompt(alerts: List[Dict[str, Any]], graph_data: Optional[List[Dict[str, Any]]] = None) -> str:
    """สร้าง prompt สำหรับ Bedrock AI แบบ 2 ส่วน (alerts table + graph analysis)"""
    
    # ส่วนที่ 1: ตาราง Cost Codes ที่ Overrun จาก alerts
    red_alerts = [a for a in alerts if a.get("status", "").upper() == "RED"]
    green_alerts = [a for a in alerts if a.get("status", "").upper() == "GREEN"]
    
    # คำนวณงบประมาณและค่าใช้จ่ายรวม
    total_budget = sum(a.get("budget", 0) for a in alerts)
    total_actual = sum(a.get("actual", 0) for a in alerts)
    
    # สร้างรายการ Cost Codes ที่ Overrun (ไม่ใช้ตาราง)
    red_cost_list = []
    for alert in red_alerts:
        cost_code = alert.get("cost_code", "N/A")
        costname = alert.get("costname", "")
        budget = alert.get("budget", 0)
        actual = alert.get("actual", 0)
        overrun = actual - budget
        
        red_cost_list.append(f"- **{cost_code}** ({costname}): งบประมาณ {budget:,.0f} บาท, ค่าใช้จ่ายจริง {actual:,.0f} บาท, Overrun {overrun:,.0f} บาท")
    
    cost_code_summary = "\n".join(red_cost_list) if red_cost_list else "ไม่พบข้อมูล Overrun"
    
    # ส่วนที่ 2: วิเคราะห์เชิงลึกจาก graph_data
    graph_analysis = ""
    if graph_data:
        # กรองเฉพาะ cost codes ที่ overrun
        # cost_code จาก alerts = costcode_h ใน graph_data
        red_cost_codes = [a.get("cost_code") for a in red_alerts]
        overrun_graph = [g for g in graph_data if g.get("costcode_h") in red_cost_codes]
        
        # สร้างข้อมูลสำหรับวิเคราะห์
        graph_summary = []
        for cost_code_h in red_cost_codes:
            code_data = [g for g in overrun_graph if g.get("costcode_h") == cost_code_h]
            if code_data:
                # เรียง sort ตาม ym
                code_data_sorted = sorted(code_data, key=lambda x: x.get("ym", ""))
                latest = code_data_sorted[-1] if code_data_sorted else {}
                
                pm_name = latest.get("pm_emp_name", "ไม่ระบุ")
                taskname = latest.get("taskname", "ไม่ระบุ")
                
                # สร้างรายละเอียดรายเดือน เพื่อวิเคราะห์ว่า overrun เกิดตั้งแต่เดือนไหน
                monthly_details = []
                for data in code_data_sorted:
                    ym = data.get("ym", "")
                    budget = data.get("amount_plan_today", 0)
                    actual = data.get("amount_acc_today", 0)
                    progress = data.get("progress_ym_acc", 0)
                    overrun_amount = actual - budget
                    overrun_status = "🔴 OVERRUN" if actual > budget else "🟢 OK"
                    
                    # แปลง ym เป็นชื่อเดือน (เช่น 202501 -> ม.ค. 2025)
                    month_name = ""
                    if ym and len(ym) >= 6:
                        year = ym[:4]
                        month = ym[4:6]
                        month_names = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", 
                                       "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
                        try:
                            month_name = f"{month_names[int(month)]} {year}"
                        except:
                            month_name = ym
                    else:
                        month_name = ym
                    
                    monthly_details.append(
                        f"    - {month_name}: งบ {budget:,.0f} | จริง {actual:,.0f} | ความก้าวหน้า {progress:.1f}% | {overrun_status}"
                    )
                
                months = [d.get("ym") for d in code_data_sorted if d.get("ym")]
                
                # รวม cost codes ย่อยที่เกี่ยวข้อง
                sub_cost_codes = list(set([d.get("costcode") for d in code_data_sorted if d.get("costcode")]))
                
                graph_summary.append(f"""
- **Cost Code หลัก: {cost_code_h}** ({taskname})
  - PM ผู้รับผิดชอบ: {pm_name}
  - Cost Codes ย่อยที่เกี่ยวข้อง: {', '.join(sub_cost_codes)}
  - จำนวนเดือนที่ติดตาม: {len(months)} เดือน
  - รายละเอียดรายเดือน:
{chr(10).join(monthly_details)}""")
        
        graph_analysis = "\n".join(graph_summary) if graph_summary else "ไม่มีข้อมูล graph สำหรับวิเคราะห์"
    
    report_date = alerts[0].get("report_date", "N/A") if alerts else "N/A"
    project_name = alerts[0].get("project_name", "N/A") if alerts else "N/A"
    
    return f"""
คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์งบประมาณโครงการ  
หน้าที่ของคุณคือจัดทำรายงานสรุปสำหรับผู้บริหารในรูปแบบที่อ่านง่ายและมีโครงสร้างชัดเจน

**ข้อกำหนดสำคัญ:**
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

**รายการ Cost Codes ที่ Overrun (Status = RISK)**
{cost_code_summary}

---

**📈 ข้อมูลเชิงลึกจากการติดตามรายเดือน (Graph Analysis)**
{graph_analysis}

---

กรุณาจัดทำรายงานโดยใช้รูปแบบนี้เท่านั้น:

📊 **สรุปสถานการณ์โครงการ**
วิเคราะห์ภาพรวมของสถานการณ์งบประมาณและผลกระทบต่อโครงการ

⚠️ **Cost Codes ที่ต้องติดตามเร่งด่วน**
วิเคราะห์ Cost Codes ที่มีปัญหารุนแรง แบ่งตามระดับความรุนแรง
**สำคัญ:** วิเคราะห์ว่า overrun เกิดขึ้นในช่วงเดือนใด โดยดูจากข้อมูล Graph Analysis ด้านบน
- ระบุว่า cost code ไหนบ้างที่ overrun
- cost code ที่ overrun มาจาก task ไหนบ้าง
- ระบุชื่อ PM ผู้รับผิดชอบแต่ละ cost code
- วิเคราะห์ว่าสถานการณ์เริ่มเสื่อมตั้งแต่เดือนใด (ดูจากช่วงเวลาที่มีข้อมูล)

🧐 **การวิเคราะห์สาเหตุ**
วิเคราะห์ปัจจัยที่อาจก่อให้เกิด Overrun โดยพิจารณาจาก:
- ช่วงเวลาที่เริ่มมีปัญหา
- Task ที่เกี่ยวข้อง
- PM ผู้รับผิดชอบ
**ปัญหาไม่ได้มาจาก PM หลายคนเพราะใน 1 แผนงานจะมี PM แค่คนเดียว**

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
            file_key = latest_file['key']
            st.info(f"📅 ใช้ข้อมูลจากไฟล์: {file_key} (วันที่: {latest_file['date'].strftime('%d/%m/%Y')})")
            
            # ดึง date_str จากชื่อไฟล์ (เช่น batch/20251015_3_alerts.json -> 20251015)
            import re
            date_match = re.search(r'(\d{8})', file_key)
            file_date_str = date_match.group(1) if date_match else None
            
            # ดึงข้อมูล
            data = fetch_alert_data(CONFIG["OVERRUN_BUCKET"], file_key)
            
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
                
                # แสดงตารางเฉพาะ field ที่ต้องการ พร้อม status
                df = pd.DataFrame(alerts)
                
                # คำนวณ Overrun %
                df['overrun_pct'] = df.apply(
                    lambda row: ((row['actual'] - row['budget']) / row['budget'] * 100) if row.get('budget', 0) > 0 else 0,
                    axis=1
                )
                
                # ฟังก์ชันสำหรับแปลง status
                def status_text(s):
                    s = str(s).upper()
                    if s == "RED":
                        return "🔴 RISK"
                    elif s == "GREEN":
                        return "🟢 SAFE"
                    else:
                        return s
                
                # เลือกเฉพาะคอลัมน์ที่ต้องการ (ใช้ reindex เพื่อป้องกัน KeyError)
                selected_columns = ["plan_code", "cost_code", "costname", "budget", "actual", "overrun_pct", "eac", "status"]
                
                # สร้าง DataFrame ใหม่ โดยใช้ reindex เพื่อจัดการคอลัมน์ที่หายไป
                df_display = df.reindex(columns=selected_columns, fill_value="")
                
                # เปลี่ยนชื่อคอลัมน์
                df_display = df_display.rename(columns={
                    "plan_code": "Plan Code",
                    "cost_code": "Cost Code",
                    "costname": "Cost Name",
                    "budget": "BCWP",
                    "actual": "ACWP",
                    "overrun_pct": "Overrun %",
                    "eac": "EAC",
                    "status": "Status"
                })
                
                # แปลง status
                df_display["Status"] = df_display["Status"].apply(status_text)
                
                # Format Overrun % 
                df_display["Overrun %"] = df_display["Overrun %"].apply(lambda x: f"{x:.1f}%" if x != "" else "")
                
                st.dataframe(df_display, use_container_width=True)
                
                # สร้าง prompt และเรียก LLM
                if red_count > 0:
                    st.subheader("🧾 Executive Summary (AI Analysis)")
                    st.info("🤖 กำลังวิเคราะห์ข้อมูลด้วย AI...")
                    
                    # ดึงข้อมูล graph สำหรับวิเคราะห์เชิงลึก (ใช้ date จากชื่อไฟล์)
                    graph_data = None
                    
                    if file_date_str:
                        graph_data = fetch_graph_data(CONFIG["OVERRUN_BUCKET"], file_date_str)
                        if not graph_data:
                            st.warning(f"⚠️ ไม่พบข้อมูล graph สำหรับการวิเคราะห์เชิงลึก")
                    else:
                        st.error("❌ ไม่สามารถดึงวันที่จากชื่อไฟล์ alerts ได้")
                        graph_data = None
                    
                    prompt = build_llm_prompt(alerts, graph_data)
                    summary = call_bedrock(prompt)
                    st.markdown(summary)
                    
                    # บันทึก report ลง S3
                    report_date = alerts[0].get("report_date", datetime.now().strftime("%Y-%m-%d")) if alerts else datetime.now().strftime("%Y-%m-%d")
                    project_name = alerts[0].get("plan_code", "MG1") if alerts else "MG1"
                    
                    with st.spinner("💾 กำลังบันทึก report ลง S3..."):
                        save_report_to_s3(summary, report_date, project_name)
                            
                
            
else:
    st.caption("กดปุ่ม **Generate Report** เพื่อเริ่มวิเคราะห์ข้อมูล")