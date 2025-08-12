import streamlit as st
import pandas as pd
import json, re
import sqlparse
import bcrypt
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from pathlib import Path

# ============== Page & minimal styles (works even without external CSS) ==============
st.set_page_config(page_title="Cohort & SQL Assistant (Login Enabled)", layout="centered")
FALLBACK_CSS = """
.block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1100px; }
.header-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; }
.app-title { margin:0; }
.big-label { font-size: 1.6rem; font-weight: 700; margin: 0.15rem 0 0.2rem; }
.stTabs [role="tab"] { font-size: 1.15rem; padding: 0.45rem 0.8rem; }
.stMultiSelect [data-baseweb="tag"], [data-baseweb="tag"] { background: #d6ebff!important; color:#0B3954!important; border-color: rgba(58,160,255,0.35)!important; }
.dua-banner{ background-color:#EAF3FC; border-radius:8px; padding:12px 14px; margin:0.4rem 0 1.2rem; line-height:1.4; }
"""
st.markdown(f"<style>{FALLBACK_CSS}</style>", unsafe_allow_html=True)

# ============== Secrets / Optional OpenAI ==============
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", None)
OPENAI_MODEL = st.secrets.get("OPENAI_MODEL", "gpt-4")

# ============== Google Sheet settings for login + logs ==============
SHEET_KEY = st.secrets.get("GOOGLE_SHEET_KEY") or st.secrets.get("GOOGLE_SHEET_KEY_OR_URL")
USERS_TAB = st.secrets.get("GOOGLE_SHEET_TAB", "users")
LOGS_TAB = st.secrets.get("GOOGLE_SHEET_LOGS_TAB", "logs")

if not SHEET_KEY:
    st.error("Missing GOOGLE_SHEET_KEY in secrets. Add it to .streamlit/secrets.toml.")
    st.stop()

# ============== Google Sheets helpers ==============
def _get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_info(st.secrets["google_service_account"], scopes=scopes)
    except KeyError:
        st.error("Missing [google_service_account] in secrets.toml (service account JSON).")
        st.stop()
    return gspread.authorize(creds)

@st.cache_data(ttl=60)
def _open_users_ws():
    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_KEY) if (isinstance(SHEET_KEY, str) and len(SHEET_KEY) == 44) else gc.open_by_url(SHEET_KEY)
    return sh.worksheet(USERS_TAB)

def _open_logs_ws(create_if_missing=True):
    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_KEY) if (isinstance(SHEET_KEY, str) and len(SHEET_KEY) == 44) else gc.open_by_url(SHEET_KEY)
    try:
        return sh.worksheet(LOGS_TAB)
    except gspread.exceptions.WorksheetNotFound:
        if not create_if_missing:
            raise
        ws = sh.add_worksheet(title=LOGS_TAB, rows=1000, cols=5)
        ws.update("A1:E1", [["timestamp_utc", "username", "action", "outcome", "detail"]])
        return ws

# ============== Auth (bcrypt) ==============
@st.cache_data(ttl=60)
def load_users_df() -> pd.DataFrame:
    ws = _open_users_ws()
    rows = ws.get_all_records()
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["username", "password_hash", "role", "active"])
    df.columns = [c.strip().lower() for c in df.columns]
    for col in ["username", "password_hash"]:
        if col not in df.columns:
            st.error(f"Users sheet missing '{col}' column.")
            st.stop()
    if "role" not in df.columns:
        df["role"] = ""
    if "active" not in df.columns:
        df["active"] = True
    df["username"] = df["username"].astype(str).str.strip().str.lower()
    return df

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def log_event(username: str, action: str, ok: bool, detail: str = ""):
    try:
        ws = _open_logs_ws(create_if_missing=True)
        ws.append_row([datetime.utcnow().isoformat(timespec="seconds"), username, action, "success" if ok else "fail", detail])
    except Exception:
        pass  # Ignore logging failures to not break UX

def login_form() -> bool:
    st.title("🔐 Sign in")
    st.caption("Authorized fellows only. Use your assigned credentials.")

    if "login_attempts" not in st.session_state:
        st.session_state.login_attempts = {}

    col1, col2 = st.columns(2)
    with col1:
        username = st.text_input("Username").strip().lower()
    with col2:
        password = st.text_input("Password", type="password")

    attempts = st.session_state.login_attempts.get(username, 0)
    locked = attempts >= 5
    submit = st.button("Sign in", type="primary", disabled=locked)

    if locked:
        st.error("Too many failed attempts. Please try again later.")
        return False
    if not submit:
        return False

    df = load_users_df()
    row = df.loc[df["username"] == username]
    if row.empty:
        st.error("Invalid username or password.")
        st.session_state.login_attempts[username] = attempts + 1
        log_event(username, "login", False, "user_not_found")
        return False

    if not bool(row.iloc[0].get("active", True)):
        st.error("This account is inactive. Contact the TA.")
        log_event(username, "login", False, "inactive")
        return False

    hashed = str(row.iloc[0]["password_hash"])
    if not verify_password(password, hashed):
        st.error("Invalid username or password.")
        st.session_state.login_attempts[username] = attempts + 1
        log_event(username, "login", False, "bad_password")
        return False

    # success
    st.session_state.login_attempts[username] = 0
    st.session_state["auth_ok"] = True
    st.session_state["user"] = username
    st.session_state["role"] = str(row.iloc[0].get("role", "") or "")
    log_event(username, "login", True)
    st.success("Signed in.")
    st.rerun()
    return True

def require_login() -> bool:
    return bool(st.session_state.get("auth_ok")) or login_form()

def logout_button():
    with st.sidebar:
        st.markdown("---")
        if st.button("Log out"):
            user = st.session_state.get("user", "")
            for k in ["auth_ok", "user", "role"]:
                st.session_state.pop(k, None)
            log_event(user, "logout", True)
            st.rerun()


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

# ==================== Data model selector (larger label) ====================
st.markdown('<div class="big-label">Data model</div>', unsafe_allow_html=True)
schema_choice = st.radio("", ["i2b2", "OMOP"], horizontal=True, key="schema_choice")
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
    st.subheader(f"Interactive Cohort Builder ({schema_choice} schema)")
    st.caption(f"Working schema: **{schema_choice}**")

    selected_tables = st.multiselect(
        "Choose tables:",
        list(schema.keys()),
        help="Pick one or more tables from the selected schema."
    )

    table_configs = {}
    for table in selected_tables:
        st.markdown(f"### `{table}`")
        cols = st.multiselect(
            f"Columns to include from `{table}`:",
            schema[table],
            default=schema[table],
            key=f"cols_{schema_choice}_{table}",
            help="Select columns you want in the output."
        )
        filter_ = st.text_input(
            f"Optional SQL WHERE clause for `{table}`:",
            key=f"filter_{schema_choice}_{table}",
            help="Example (i2b2): `sex_cd = 'F' AND birth_date >= '1970-01-01'`\n"
                 "Example (OMOP): `year_of_birth <= 2007` OR `measurement_concept_id = 3004249`"
        )
        if ";" in filter_:
            st.warning("It looks like your filter contains a semicolon (`;`). Remove it to avoid SQL issues.", icon="🛑")
        table_configs[table] = {"columns": cols, "filter": filter_}

    if st.button("Generate & Examples", key=f"generate_{schema_choice}_cohort"):
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
                st.error(f"❌ {e}")
            else:
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
    st.subheader("LLM-Powered SQL Query Generator")
    st.caption(f"Working schema: **{schema_choice}**")

    user_question = st.text_input(
        "What do you want to query?",
        key=f"user_request_{schema_choice}",
        help="Example: 'Count unique patients by year' or 'Join visits with conditions for CAD'."
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
                st.error(f"❌ {e}")
            else:
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
