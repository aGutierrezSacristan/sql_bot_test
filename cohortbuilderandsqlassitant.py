import streamlit as st
import pandas as pd
import openai
import json
import re
import sqlparse

# ==================== App & API setup ====================
st.set_page_config(page_title="Cohort & SQL Assistant (Fellowship Edition)", layout="centered")
openai.api_key = st.secrets["OPENAI_API_KEY"]  # Add to .streamlit/secrets.toml

# ==================== Global Styles (Item 3: polish banner & layout) ====================
st.markdown(
    '''
    <style>
    /* Tighter vertical spacing & clean layout */
    .block-container { padding-top: 1.25rem; padding-bottom: 2rem; max-width: 1100px; }
    /* Slim alerts */
    div[data-testid="stAlert"] { margin-top: 0.5rem; margin-bottom: 0.75rem; }
    /* Code readability */
    code, pre { font-size: 0.92rem !important; }
    /* Tabs spacing */
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; }
    /* Section titles */
    h2, h3 { margin-top: 0.6rem; }
    /* Header bar */
    .header-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; }
    .app-title { margin: 0; }
    .subtitle { color:#475569; margin-top: 0.2rem; }
    </style>
    ''',
    unsafe_allow_html=True
)

# ==================== Persistent PHI warning (Item 3) ====================
def phi_banner():
    st.info(
        "🚨 **Do not copy/paste results or patient-level data below.** "
        "Use this only for query generation & examples; follow institutional data policies.",
        icon="⚠️",
    )

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

# ==================== OpenAI helper ====================
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

# ==================== Header (Item 1: branding header) ====================
with st.container():
    st.markdown('<div class="header-bar">', unsafe_allow_html=True)
    col1, col2 = st.columns([0.70, 0.30])
    with col1:
        st.markdown("<h1 class='app-title'>Cohort & SQL Assistant</h1>", unsafe_allow_html=True)
        st.caption("Fellowship Edition • i2b2 & OMOP • Guided for mixed-background researchers")
    with col2:
        st.write("")  # small spacer
        schema_choice = st.radio("Data model", ["i2b2", "OMOP"], horizontal=True, key="schema_choice_top")
    st.markdown("</div>", unsafe_allow_html=True)

phi_banner()

# Determine active schema
if schema_choice == "i2b2":
    schema_description = I2B2_SCHEMA_DESC
    schema = I2B2_SCHEMA
else:
    schema_description = OMOP_SCHEMA_DESC
    schema = OMOP_SCHEMA

# ==================== Onboarding (Item 4: Quick start + Presets) ====================
with st.expander("🧭 Quick start (60 seconds)", expanded=False):
    st.markdown('''
**How to use**
1) Pick a **Data model** above (i2b2 or OMOP)  
2) In **Cohort Builder**, choose tables and (optional) filters  
3) Click **Generate** to see SQL, examples, and R DBI code  
4) Or use **Open Question to SQL** and ask in plain English
''')

# Presets
preset = st.selectbox(
    "Try a preset example",
    ["— None —",
     "i2b2: Encounters with a specific concept_cd",
     "OMOP: Adults (>=18) with a condition and a measurement"],
    help="Load a minimal request so newcomers see the flow."
)

def load_preset(name: str):
    # Initialize defaults to avoid KeyErrors
    st.session_state.setdefault("selected_tables", [])
    # Clear old table-specific states
    for k in list(st.session_state.keys()):
        if k.startswith("cols_") or k.startswith("filter_"):
            del st.session_state[k]

    if name.startswith("i2b2"):
        st.session_state["schema_choice_top"] = "i2b2"
        st.session_state["selected_tables"] = ["observation_fact", "patient_dimension"]
        st.session_state["cols_i2b2_observation_fact"] = I2B2_SCHEMA["observation_fact"]
        st.session_state["cols_i2b2_patient_dimension"] = I2B2_SCHEMA["patient_dimension"]
        st.session_state["filter_i2b2_observation_fact"] = "concept_cd = 'ICD9:250.00'"
        st.session_state["filter_i2b2_patient_dimension"] = ""
    elif name.startswith("OMOP"):
        st.session_state["schema_choice_top"] = "OMOP"
        st.session_state["selected_tables"] = ["condition_occurrence", "measurement", "person"]
        st.session_state["cols_OMOP_condition_occurrence"] = OMOP_SCHEMA["condition_occurrence"]
        st.session_state["cols_OMOP_measurement"] = OMOP_SCHEMA["measurement"]
        st.session_state["cols_OMOP_person"] = OMOP_SCHEMA["person"]
        st.session_state["filter_OMOP_condition_occurrence"] = "condition_concept_id = 201826"  # T2DM example
        st.session_state["filter_OMOP_measurement"] = "measurement_concept_id = 3004249"       # HbA1c example
        st.session_state["filter_OMOP_person"] = "year_of_birth <= 2007"                       # >=18 as of 2025
    else:
        st.session_state["selected_tables"] = []

if st.button("Load preset"):
    if preset != "— None —":
        load_preset(preset)
        st.success("Preset loaded. Scroll to Cohort Builder below.", icon="✅")

# ==================== Tabs ====================
tab1, tab2 = st.tabs(["🧬 Cohort Builder", "🤖 Open Question to SQL"])

# -------------------- Cohort Builder --------------------
with tab1:
    st.subheader(f"Interactive Cohort Builder ({schema_choice} schema)")
    st.caption(f"Working schema: **{schema_choice}**")

    selected_tables = st.multiselect(
        "Choose tables:",
        list(schema.keys()),
        default=st.session_state.get("selected_tables", []),
        key="selected_tables",
        help="Pick one or more tables from the selected schema."
    )

    table_configs = {}
    for table in selected_tables:
        st.markdown(f"### 🗃️ `{table}`")
        cols = st.multiselect(
            f"Columns to include from `{table}`:",
            schema[table],
            default=st.session_state.get(f"cols_{schema_choice}_{table}", schema[table]),
            key=f"cols_{schema_choice}_{table}",
            help="Select columns you want in the output."
        )
        # (Item 8) Tooltips & guardrails for filters
        filter_ = st.text_input(
            f"Optional SQL WHERE clause for `{table}`:",
            value=st.session_state.get(f"filter_{schema_choice}_{table}", ""),
            key=f"filter_{schema_choice}_{table}",
            help="Example (i2b2): `sex_cd = 'F' AND birth_date >= '1970-01-01'`\n"
                 "Example (OMOP): `year_of_birth <= 2007` OR `measurement_concept_id = 3004249`"
        )
        if ";" in filter_:
            st.warning("It looks like your filter contains a semicolon (`;`). Remove it to avoid SQL issues.", icon="🛑")
        table_configs[table] = {"columns": cols, "filter": filter_}

    if st.button("🚀 Generate Query & Examples", key=f"generate_{schema_choice}_cohort"):
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
                st.subheader("✅ Generated SQL Query")
                st.code(sqlparse.format(result["sql"], reindent=True, keyword_case='upper'), language="sql")
                if "explanation" in result:
                    st.markdown("### 🧠 Explanation")
                    st.markdown(result["explanation"])
                if "r_query" in result:
                    st.markdown("### 📦 R Code (DBI)")
                    st.code(result["r_query"], language="r")
                if "input_tables" in result:
                    st.markdown("### 📥 Example Input Tables")
                    for tbl, rows in result["input_tables"].items():
                        st.markdown(f"**`{tbl}`**")
                        st.dataframe(pd.DataFrame(rows))
                if "output_table" in result:
                    st.markdown("### 📤 Example Output Table")
                    st.dataframe(pd.DataFrame(result["output_table"]))

# -------------------- Free-text SQL --------------------
with tab2:
    st.subheader("LLM-Powered SQL Query Generator")
    st.caption(f"Working schema: **{schema_choice}**")

    user_question = st.text_input(
        "💬 What do you want to query?",
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
                st.subheader("✅ Generated SQL Query")
                st.code(sqlparse.format(result["sql"], reindent=True, keyword_case='upper'), language="sql")
                if "explanation" in result:
                    st.markdown("### 🧠 Explanation")
                    st.markdown(result["explanation"])
                if "r_query" in result:
                    st.markdown("### 📦 R Code (DBI)")
                    st.code(result["r_query"], language="r")
                if "input_tables" in result:
                    st.markdown("### 📥 Example Input Tables")
                    for tbl, rows in result["input_tables"].items():
                        st.markdown(f"**`{tbl}`**")
                        st.dataframe(pd.DataFrame(rows))
                if "output_table" in result:
                    st.markdown("### 📤 Example Output Table")
                    st.dataframe(pd.DataFrame(result["output_table"]))

# ==================== Schema Reference (Item 9: clarity) ====================
with st.expander("📘 Schema fields reference"):
    st.code(I2B2_SCHEMA_DESC if schema_choice=="i2b2" else OMOP_SCHEMA_DESC)

# ==================== Footer (Item 1: footer + Item 9 clarity) ====================
st.markdown(
    '''
    <hr style="margin-top:1.25rem;margin-bottom:0.5rem;">
    <div style="display:flex;justify-content:space-between;align-items:center; font-size:0.9rem; opacity:0.9;">
      <div>Questions or issues? <b>Contact XXX</b></div>
      <div>Built with Streamlit</div>
    </div>
    ''',
    unsafe_allow_html=True
)
