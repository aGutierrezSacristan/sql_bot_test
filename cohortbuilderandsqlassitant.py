# ==================== Page config MUST be first ====================
import streamlit as st
st.set_page_config(page_title="Cohort & SQL Assistant", layout="centered")

# ==================== Imports ====================
import hashlib
import pandas as pd
import openai
import json
import re
import sqlparse
from pathlib import Path
from datetime import datetime

# NEW imports for logging to Google Sheets
import gspread
from google.oauth2.service_account import Credentials
import pytz
import unicodedata

# ==================== Simple Login (public Google Sheet via CSV) ====================
@st.cache_data(ttl=300, show_spinner=False)
def load_users_from_public_csv(sheet_key: str, worksheet_name: str = "users") -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_key}/gviz/tq?tqx=out:csv&sheet={worksheet_name}"
    df = pd.read_csv(url, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    if "Username" not in df.columns or "Password" not in df.columns:
        raise ValueError("Sheet must have 'Username' and 'Password' columns.")
    return df

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def verify_login(username: str, password: str, users_df: pd.DataFrame) -> bool:
    if not username or not password or users_df.empty:
        return False
    hashed_input = hash_password(password)
    match = users_df[
        (users_df["Username"].astype(str) == str(username)) &
        (users_df["Password"].astype(str) == hashed_input)
    ]
    return not match.empty

# ==================== Logging helpers (service account, same sheet different tabs) ====================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

@st.cache_resource(show_spinner=False)
def gspread_client():
    creds = Credentials.from_service_account_info(st.secrets["google_service_account"], scopes=SCOPES)
    return gspread.authorize(creds)

def connect_worksheet(sheet_id: str, worksheet_name: str):
    gc = gspread_client()
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=10)
        # header row depends on tab
        if worksheet_name == "logs":
            ws.append_row(["Timestamp", "Username", "Action", "Role"])
        elif worksheet_name == "events":
            ws.append_row(["Timestamp", "Username", "Event", "Details"])
    return ws

def register_log(username: str, action: str, role: str = ""):
    """Append a log row to the 'logs' tab."""
    try:
        sheet_id = st.secrets["GOOGLE_SHEET_KEY"].strip()
        ws = connect_worksheet(sheet_id, "logs")
        tz = pytz.timezone("America/New_York")  # Boston time
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        username_norm = unicodedata.normalize("NFKC", (username or "").strip())
        ws.append_row([now, username_norm, action, role], value_input_option="RAW")
    except Exception as e:
        st.warning(f"⚠️ Could not register log: {e}")

def register_event(event: str, details: dict | None = None):
    """Append an interaction event to the 'events' tab."""
    try:
        sheet_id = st.secrets["GOOGLE_SHEET_KEY"].strip()
        ws = connect_worksheet(sheet_id, "events")
        tz = pytz.timezone("America/New_York")
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        username = unicodedata.normalize("NFKC", (st.session_state.get("username") or "").strip())
        payload = json.dumps(details or {}, ensure_ascii=False)[:5000]  # cap size
        ws.append_row([now, username, event, payload], value_input_option="RAW")
    except Exception as e:
        st.warning(f"⚠️ Could not register event: {e}")

# --- one-time event helper to avoid spam on reruns ---
if "_logged_once" not in st.session_state:
    st.session_state._logged_once = set()

def log_once(event: str, details: dict | None = None):
    token = (event, json.dumps(details or {}, sort_keys=True))
    if token not in st.session_state._logged_once:
        st.session_state._logged_once.add(token)
        register_event(event, details)

# -------------------- Session flags --------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""

# -------------------- Login gate --------------------
def login_gate():
    st.markdown("### 🔐 Login")
    user = st.text_input("Username", key="login_user")
    pwd  = st.text_input("Password", type="password", key="login_pwd")
    login_clicked = st.button("Login", type="primary", on_click=lambda: register_event("login_button_clicked"))
    if login_clicked:
        try:
            users_df = load_users_from_public_csv(st.secrets["GOOGLE_SHEET_KEY"], "users")
        except Exception as e:
            st.error(f"Could not load user list. Check GOOGLE_SHEET_KEY / sheet sharing.\n\n{e}")
            register_log("", f"login_users_load_failed: {e}")
            return
        if verify_login(user.strip(), pwd, users_df):
            register_log(user, "login")
            st.session_state.logged_in = True
            st.session_state.username = user.strip()
            st.success("Login successful! 🎉")
            st.rerun()
        else:
            register_log(user, "login_failed")
            st.error("Invalid username or password.")

# Gate the rest of the app
if not st.session_state.logged_in:
    login_gate()
    st.stop()

# Optional: sidebar logout
with st.sidebar:
    st.markdown(f"**Logged in as:** {st.session_state.username}")
    if st.button("Logout", on_click=lambda: register_event("logout_button_clicked")):
        register_log(st.session_state.get("username",""), "logout")
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.success("Logged out.")
        st.rerun()

# ==================== App & API setup ====================
openai.api_key = st.secrets["OPENAI_API_KEY"]

# ==================== Load external CSS (style.css) ====================
def load_css():
    css_path = Path(__file__).with_name("style.css")
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)

# Fallback minimal CSS in case style.css is missing (kept tiny)
FALLBACK_CSS = '''
.block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1100px; }
.stTabs [role="tab"] { font-size: 1.1rem; padding: 0.5rem 0.75rem; }
.big-label { font-size: 1.2rem; font-weight: 700; margin: 0.35rem 0 0.25rem; }
.stMultiSelect [data-baseweb="tag"], [data-baseweb="tag"] {
    background-color: #d6ebff !important;
    color: #003366 !important;
    border-color: rgba(58,160,255,0.35) !important;
}
div[data-testid="stAlert"] { margin-top: 0.5rem; margin-bottom: 0.9rem; }
code, pre { font-size: 0.92rem !important; }
h2, h3 { margin-top: 0.6rem; }
.header-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; }
.app-title { margin: 0; }
'''

st.markdown(f"<style>{FALLBACK_CSS}</style>", unsafe_allow_html=True)
load_css()

# ==================== Schemas ====================
I2B2_SCHEMA_DESC = '''
- observation_fact: encounter_num, patient_num, concept_cd, start_date
- patient_dimension: patient_num, birth_date, death_date, sex_cd, race_cd, ethnicity_cd, language_cd, marital_status_cd, zip_cd
- concept_dimension: concept_cd, name_char
- visit_dimension: encounter_id, patient_num, start_date, end_date
'''
I2B2_SCHEMA = {
    "patient_dimension": [
        "patient_num", "birth_date", "death_date", "sex_cd", "race_cd",
        "ethnicity_cd", "language_cd", "marital_status_cd", "zip_cd"
    ],
    "observation_fact": [
        "encounter_num", "patient_num", "concept_cd", "start_date"
    ],
    "concept_dimension": [
        "concept_cd", "name_char"
    ],
    "visit_dimension": [
        "encounter_id", "patient_num", "start_date", "end_date"
    ]
}

OMOP_SCHEMA_DESC = '''
- person: person_id, gender_concept_id, year_of_birth, race_concept_id, ethnicity_concept_id
- visit_occurrence: visit_occurrence_id, person_id, visit_concept_id, visit_start_date, visit_end_date
- condition_occurrence: condition_occurrence_id, person_id, condition_concept_id, condition_start_date
- measurement: measurement_id, person_id, measurement_concept_id, measurement_date, value_as_number, unit_concept_id
- observation: observation_id, person_id, observation_concept_id, observation_date, value_as_string
- drug_exposure: drug_exposure_id, person_id, drug_concept_id, drug_exposure_start_date, drug_exposure_end_date
'''
OMOP_SCHEMA = {
    "person": [
        "person_id","gender_concept_id","year_of_birth","race_concept_id","ethnicity_concept_id"
    ],
    "visit_occurrence": [
        "visit_occurrence_id","person_id","visit_concept_id","visit_start_date","visit_end_date"
    ],
    "condition_occurrence": [
        "condition_occurrence_id","person_id","condition_concept_id","condition_start_date"
    ],
    "measurement": [
        "measurement_id","person_id","measurement_concept_id","measurement_date","value_as_number","unit_concept_id"
    ],
    "observation": [
        "observation_id","person_id","observation_concept_id","observation_date","value_as_string"
    ],
    "drug_exposure": [
        "drug_exposure_id","person_id","drug_concept_id","drug_exposure_start_date","drug_exposure_end_date"
    ]
}

# ==================== Helper ====================
def call_openai_json(prompt: str) -> dict:
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    content = response.choices[0].message.content.strip()
    m = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if not m:
        raise ValueError("No valid JSON found in response.")
    return json.loads(m.group(1))

# ==================== Header ====================
with st.container():
    st.markdown('<div class="header-bar">', unsafe_allow_html=True)
    col1, col2 = st.columns([0.8, 0.2])
    with col1:
        st.markdown("<h1 class='app-title'>Cohort & SQL Assistant</h1>", unsafe_allow_html=True)
        st.caption("• i2b2 & OMOP •")
    with col2:
        st.empty()
    st.markdown("</div>", unsafe_allow_html=True)

# ==================== How to use (new copy) ====================
with st.expander("📘 How to use", expanded=True):
    st.markdown('''
- **Choose a data model** (e.g., i2b2).
- **Decide the best approach to generate your SQL query:**
    - **Cohort Builder**
        - choose tables (e.g., `patient_dimension`)
        - unselect the columns you do not want to be included in the output table
        - add optional filters (optional SQL WHERE clause) (e.g., females, adolescents)
        - click on **"Generate & Examples"**
    - **Open Question to SQL**
        - write in plain English (e.g., boys with autism diagnosed during childhood)
''')
    log_once("how_to_view", {"section": "How to use"})

# ==================== Data model selector (larger label) ====================
st.markdown('<div class="big-label">Data model</div>', unsafe_allow_html=True)
def on_schema_change():
    register_event("schema_changed", {"schema": st.session_state.get("schema_choice")})
schema_choice = st.radio(
    "",
    ["i2b2", "OMOP"],
    horizontal=True,
    key="schema_choice",
    on_change=on_schema_change
)
if schema_choice == "i2b2":
    schema_description = I2B2_SCHEMA_DESC
    schema = I2B2_SCHEMA
else:
    schema_description = OMOP_SCHEMA_DESC
    schema = OMOP_SCHEMA

# ==================== PHI Warning (yellow triangles at start and end) ====================
st.markdown(
    """
    <div style="background-color: #eaf3fc; padding: 10px; border-radius: 5px;">
        ⚠️ <strong>Do not copy/paste results or patient-level data below.</strong> 
        Use this only for query generation &amp; examples; 
        <strong>always follow your Data Use Agreement (DUA)</strong>.&nbsp;⚠️
    </div>
    """,
    unsafe_allow_html=True
)

# ==================== Tabs (labels sized via CSS) ====================
tab1, tab2 = st.tabs(["Cohort Builder", "Open Question to SQL"])

# -------------------- Cohort Builder --------------------
with tab1:
    log_once("tab_view", {"tab": "Cohort Builder", "schema": schema_choice})
    st.subheader(f"Interactive Cohort Builder ({schema_choice} schema)")
    st.caption(f"Working schema: **{schema_choice}**")
    
    def on_tables_change():
        picked = st.session_state.get("selected_tables", [])
        register_event("tables_selected", {"schema": schema_choice, "tables": picked})

    selected_tables = st.multiselect(
    "Choose tables:",
    list(schema.keys()),
    key="selected_tables",
    help="Pick one or more tables from the selected schema.",
    on_change=on_tables_change)

    table_configs = {}
    
    def make_cols_cb(tbl_name: str):
        def _cb():
            cols = st.session_state.get(f"cols_{schema_choice}_{tbl_name}", [])
            register_event("table_columns_changed", {
                "schema": schema_choice,
                "table": tbl_name,
                "num_columns": len(cols),
                "columns_sample": cols[:10],
            })
            return _cb
        
    def make_filter_cb(tbl_name: str):
        def _cb():
            f = st.session_state.get(f"filter_{schema_choice}_{tbl_name}", "")
            register_event("table_filter_changed", {
                "schema": schema_choice,
                "table": tbl_name,
                "filter_len": len(f),
                "filter_preview": f[:200],
            })
            return _cb
    
    for table in selected_tables:
        st.markdown(f"### `{table}`")
        cols = st.multiselect(
            f"Columns to include from `{table}`:",
            schema[table],
            default=schema[table],
            key=f"cols_{schema_choice}_{table}",
            help="Select columns you want in the output.",
            on_change=make_cols_cb(table)
        )
        
        filter_ = st.text_input(
            f"Optional SQL WHERE clause for `{table}`:",
            key=f"filter_{schema_choice}_{table}",
            help="Example (i2b2): `sex_cd = 'F' AND birth_date >= '1970-01-01'`\n"
            "Example (OMOP): `year_of_birth <= 2007` OR `measurement_concept_id = 3004249`",
            on_change=make_filter_cb(table)
        )
        
        if ";" in filter_:
            st.warning("It looks like your filter contains a semicolon (`;`). Remove it to avoid SQL issues.", icon="🛑")
        table_configs[table] = {"columns": cols, "filter": filter_}

    def summarize_table_configs(configs: dict) -> dict:
        summary = {"schema": schema_choice, "tables": []}
        for t, cfg in configs.items():
            summary["tables"].append({
                "table": t,
                "num_cols": len(cfg["columns"]),
                "has_filter": bool(cfg["filter"]),
                "filter_preview": (cfg["filter"] or "")[:200],
            })
            return summary

    if st.button("Generate & Examples", key=f"generate_{schema_choice}_cohort"):
        register_event("cohort_generate_clicked", summarize_table_configs(table_configs))
        with st.spinner("Generating…"):
            desc = "I want to build a dataset with:\n"
            for table, cfg in table_configs.items():
                desc += f"- Table `{table}`: columns {cfg['columns']}"
                if cfg['filter']:
                    desc += f", filtered by `{cfg['filter']}`"
                desc += "\n"

            prompt = f'''
You are a senior data engineer and educator with deep expertise in SQL, the {schema_choice} data model, and clinical informatics.

Your task is to:
1. Generate the correct and optimized SQL query.
2. Provide realistic example rows for the input tables involved.
3. Show the expected output table rows.
4. Explain the SQL logic in simple, step-by-step terms.
5. Convert the SQL into the appropriate R DBI function:
   - Use `dbGetQuery()` for SELECT/read operations (e.g., counts, views).
   - Use `dbSendUpdate()` (or dbExecute()) for CREATE, INSERT, DELETE, or UPDATE statements.

The schema is:
{schema_description}

User request:
{desc}

Return only valid JSON inside a markdown ```json block using the following format:
```json
{{
  "sql": "...",
  "input_tables": {{ "table_name": [{{row_dict}}, ...] }},
  "output_table": [{{row_dict}}, ...],
  "explanation": "explain the SQL logic here",
  "r_query": "dbGetQuery(con, '...')"  // or dbSendUpdate depending on query type
}}
```
'''
            try:
                result = call_openai_json(prompt)
            except Exception as e:
                register_event("cohort_generate_error", {"error": str(e)[:500]})
                st.error(f"❌ {e}")
            else:
                register_event("cohort_generate_success", {
                    "sql_len": len(result.get("sql", "")),
                    "has_explanation": "explanation" in result,
                    "has_r_query": "r_query" in result,
                    "num_input_tables": len(result.get("input_tables", {})),
                    "num_output_rows": len(result.get("output_table", [])) if isinstance(result.get("output_table"), list) else None
                })

                st.subheader("Generated SQL Query")
                st.code(sqlparse.format(result["sql"], reindent=True, keyword_case='upper'), language="sql")
                if "explanation" in result:
                    st.markdown("### Explanation")
                    st.markdown(result["explanation"])
                if "r_query" in result:
                    st.markdown("### R Code (DBI)")
                    st.code(result["r_query"], language="r")
                if "input_tables" in result:
                    st.markdown("### Example Input Tables")
                    for tbl, rows in result["input_tables"].items():
                        st.markdown(f"**`{tbl}`**")
                        st.dataframe(pd.DataFrame(rows))
                if "output_table" in result:
                    st.markdown("### Example Output Table")
                    st.dataframe(pd.DataFrame(result["output_table"]))

# -------------------- Free-text SQL --------------------
with tab2:
    log_once("tab_view", {"tab": "Open Question to SQL", "schema": schema_choice})
    st.subheader("LLM-Powered SQL Query Generator")
    st.caption(f"Working schema: **{schema_choice}**")

    def on_user_question_change():
        val = st.session_state.get(f"user_request_{schema_choice}", "")
        register_event("free_text_changed", {
            "schema": schema_choice,
            "len": len(val),
            "preview": val[:200],
        })
        
    user_question = st.text_input(
        "What do you want to query?",
        key=f"user_request_{schema_choice}",
        help="Example: 'Count unique patients by year' or 'Join visits with conditions for CAD'.",
        on_change=on_user_question_change
    )

    if user_question:
        with st.spinner("Generating SQL and examples…"):
            prompt = f'''
You are a senior data engineer and educator with deep expertise in SQL, the {schema_choice} data model, and clinical informatics.

Your task is to:
1. Write the correct and optimized SQL query.
2. Provide realistic example rows for each input table.
3. Simulate the expected result table.
4. Explain the SQL logic clearly and step-by-step.
5. Generate the corresponding R DBI command:
   - Use `dbGetQuery()` for SELECT queries.
   - Use `dbSendUpdate()` (or dbExecute()) for queries that modify the DB (e.g. CREATE TABLE, INSERT).

The schema is:
{schema_description}

User request:
"{user_question}"

Return only valid JSON inside a markdown ```json block in this format:
```json
{{
  "sql": "...",
  "input_tables": {{ "table_name": [{{row_dict}}, ...] }},
  "output_table": [{{row_dict}}, ...],
  "explanation": "explain the SQL logic here",
  "r_query": "dbGetQuery(con, '...')"  // or dbSendUpdate depending on SQL
}}
```
'''
            try:
                result = call_openai_json(prompt)
            except Exception as e:
                register_event("free_text_generate_error", {"error": str(e)[:500]})
                st.error(f"❌ {e}")
            else:
                register_event("free_text_generate_success", {
                    "sql_len": len(result.get("sql", "")),
                    "has_explanation": "explanation" in result,
                    "has_r_query": "r_query" in result,
                    "num_input_tables": len(result.get("input_tables", {})),
                    "num_output_rows": len(result.get("output_table", [])) if isinstance(result.get("output_table"), list) else None
                })
                st.subheader("Generated SQL Query")
                st.code(sqlparse.format(result["sql"], reindent=True, keyword_case='upper'), language="sql")
                if "explanation" in result:
                    st.markdown("### Explanation")
                    st.markdown(result["explanation"])
                if "r_query" in result:
                    st.markdown("### R Code (DBI)")
                    st.code(result["r_query"], language="r")
                if "input_tables" in result:
                    st.markdown("### Example Input Tables")
                    for tbl, rows in result["input_tables"].items():
                        st.markdown(f"**`{tbl}`**")
                        st.dataframe(pd.DataFrame(rows))
                if "output_table" in result:
                    st.markdown("### Example Output Table")
                    st.dataframe(pd.DataFrame(result["output_table"]))

# ==================== Schema Reference ====================
with st.expander("Schema fields reference"):
    log_once("schema_reference_view", {"schema": schema_choice})
    st.code(I2B2_SCHEMA_DESC if schema_choice=="i2b2" else OMOP_SCHEMA_DESC)

# ==================== Footer ====================
st.markdown(
    '''
    <hr style="margin-top:1.25rem;margin-bottom:0.5rem;">
    <div style="display:flex;justify-content:space-between;align-items:center; font-size:0.9rem; opacity:0.9;">
      <div>Questions or issues? <b>Contact XXX</b></div>
      <div>Last Updated August 2025 • Built with Streamlit</div>
    </div>
    ''',
    unsafe_allow_html=True
)
