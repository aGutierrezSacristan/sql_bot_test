import streamlit as st
import pandas as pd
import openai
import json
import re
import sqlparse

# -------------------- App & API setup --------------------
st.set_page_config(page_title="Cohort & SQL Assistant (i2b2 / OMOP)", layout="centered")
openai.api_key = st.secrets["OPENAI_API_KEY"]  # Add to .streamlit/secrets.toml

# -------------------- Persistent PHI warning --------------------
def phi_banner():
    st.warning(
        "🚨 **Do not copy and paste any results or patient-level data below.** "
        "This tool is for query generation and examples only. Follow your institution’s data handling and disclosure policies.",
        icon="⚠️",
    )

# -------------------- Schemas --------------------
I2B2_SCHEMA_DESC = """
- observation_fact: encounter_num, patient_num, concept_cd, start_date
- patient_dimension: patient_num, birth_date, death_date, sex_cd, race_cd, ethnicity_cd, language_cd, marital_status_cd, zip_cd
- concept_dimension: concept_cd, name_char
- visit_dimension: encounter_id, patient_num, start_date, end_date
"""
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

OMOP_SCHEMA_DESC = """
- person: person_id, gender_concept_id, year_of_birth, race_concept_id, ethnicity_concept_id
- visit_occurrence: visit_occurrence_id, person_id, visit_concept_id, visit_start_date, visit_end_date
- condition_occurrence: condition_occurrence_id, person_id, condition_concept_id, condition_start_date
- measurement: measurement_id, person_id, measurement_concept_id, measurement_date, value_as_number, unit_concept_id
- observation: observation_id, person_id, observation_concept_id, observation_date, value_as_string
- drug_exposure: drug_exposure_id, person_id, drug_concept_id, drug_exposure_start_date, drug_exposure_end_date
"""
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

# -------------------- OpenAI helper --------------------
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

# -------------------- UI --------------------
st.title("🧪 Cohort & SQL Assistant")
phi_banner()

schema_choice = st.radio("Choose data model", ["i2b2", "OMOP"], horizontal=True)
if schema_choice == "i2b2":
    schema_description = I2B2_SCHEMA_DESC
    schema = I2B2_SCHEMA
    st.caption("Current schema: **i2b2**")
else:
    schema_description = OMOP_SCHEMA_DESC
    schema = OMOP_SCHEMA
    st.caption("Current schema: **OMOP CDM**")

tab1, tab2 = st.tabs(["🧬 Cohort Builder", "🤖 Open Question to SQL"])

with tab1:
    st.title(f"🧬 Interactive Cohort Builder ({schema_choice} schema)")
    st.markdown("""
    Select columns & filters. I’ll generate:
    - A **SQL query**
    - Example **input/output tables**
    - A **correct R DBI call**
    - A simple **explanation**
    """)

    selected_tables = st.multiselect("Choose tables:", list(schema.keys()))
    table_configs = {}
    for table in selected_tables:
        st.markdown(f"### 🗃️ `{table}`")
        cols = st.multiselect(
            f"Columns to include from `{table}`:",
            schema[table],
            default=schema[table],
            key=f"cols_{schema_choice}_{table}"
        )
        filter_ = st.text_input(
            f"Optional SQL WHERE clause for `{table}`:",
            key=f"filter_{schema_choice}_{table}"
        )
        table_configs[table] = {"columns": cols, "filter": filter_}

    if st.button("🚀 Generate Query & Examples", key=f"generate_{schema_choice}_cohort"):
        with st.spinner("Generating…"):
            desc = "I want to build a dataset with:\n"
            for table, cfg in table_configs.items():
                desc += f"- Table `{table}`: columns {cfg['columns']}"
                if cfg['filter']:
                    desc += f", filtered by `{cfg['filter']}`"
                desc += "\n"

            prompt = f"""
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
"""
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

with tab2:
    st.title("🤖 LLM-Powered SQL Query Generator")
    st.markdown("""
    Ask any question about the selected schema. I’ll return:
    - A **SQL query**
    - Example **input/output**
    - A **R DBI-compatible call**
    - A simple **explanation**
    """)

    user_question = st.text_input("💬 What do you want to query?", key=f"user_request_{schema_choice}")

    if user_question:
        with st.spinner("Generating SQL and examples…"):
            prompt = f"""
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
"""
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

