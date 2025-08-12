
import streamlit as st
import hashlib
import gspread
from google.oauth2.service_account import Credentials

# ==================== LOGIN CONFIGURATION ====================
GOOGLE_SHEET_KEY = st.secrets["GOOGLE_SHEET_KEY"].strip()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def connect_worksheet(sheet_key, worksheet_name):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["google_service_account"],
        scopes=scopes
    )
    client = gspread.authorize(credentials)
    return client.open_by_key(sheet_key).worksheet(worksheet_name)

def verify_login(username, input_password):
    sheet = connect_worksheet(GOOGLE_SHEET_KEY, "users")
    records = sheet.get_all_records()
    input_hash = hash_password(input_password)
    for row in records:
        if row["Username"] == username and row["Password"] == input_hash:
            st.session_state["user_role"] = row.get("Role", "user")
            st.session_state["username"] = username
            return True
    return False

# ==================== LOGIN PAGE ====================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if verify_login(username, password):
            st.session_state["logged_in"] = True
            st.success("Login successful!")
            st.experimental_rerun()
        else:
            st.error("Invalid username or password")
    st.stop()


import streamlit as st
import pandas as pd
import openai
import json
import re
import sqlparse
from pathlib import Path

# ==================== App & API setup ====================
st.set_page_config(page_title="Cohort & SQL Assistant", layout="centered")
openai.api_key = st.secrets["OPENAI_API_KEY"]  # Add to .streamlit/secrets.toml

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
