import streamlit as st
import pandas as pd
import openai
import json
import re
import sqlparse

st.set_page_config(page_title="Cohort & SQL Assistant", layout="centered")
openai.api_key = st.secrets["OPENAI_API_KEY"]

schema_description = """
- observation_fact: encounter_num, patient_num, concept_cd, start_date  
- patient_dimension: patient_num, birth_date, death_date, sex_cd, race_cd, ethnicity_cd, language_cd, marital_status_cd, zip_cd  
- concept_dimension: concept_cd, name_char  
- visit_dimension: encounter_id, patient_num, start_date, end_date
"""

schema = {
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

tab1, tab2 = st.tabs(["🧬 Cohort Builder", "🤖 Open Question to SQL"])

with tab1:
    st.title("🧬 Interactive Cohort Builder (i2b2 schema)")
    st.markdown("""
    Select columns & filters from i2b2 schema tables. I’ll generate:
    - A **MySQL query**
    - Example **input/output tables**
    - A **correct R DBI call**
    - A simple **explanation**
    """)

    selected_tables = st.multiselect("Choose tables:", list(schema.keys()))
    table_configs = {}
    for table in selected_tables:
        st.markdown(f"### 🗃️ `{table}`")
        cols = st.multiselect(f"Columns to include from `{table}`:", schema[table], default=schema[table], key=f"cols_{table}")
        filter_ = st.text_input(f"Optional SQL WHERE clause for `{table}`:", key=f"filter_{table}")
        table_configs[table] = {"columns": cols, "filter": filter_}

    if st.button("🚀 Generate Query & Examples", key="generate_cohort"):
        with st.spinner("Generating…"):
            desc = "I want to build a dataset with:\n"
            for table, cfg in table_configs.items():
                desc += f"- Table `{table}`: columns {cfg['columns']}"
                if cfg['filter']:
                    desc += f", filtered by `{cfg['filter']}`"
                desc += "\n"

            prompt = f"""
You are a senior data engineer and educator with deep expertise in SQL, the i2b2 data model, and clinical informatics.

Your task is to:
1. Generate the correct and optimized MySQL query.
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

            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            content = response.choices[0].message.content.strip()
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)

            if not json_match:
                st.error("❌ No valid JSON found in response.")
                st.text_area("Raw output:", content, height=300)
            else:
                try:
                    result = json.loads(json_match.group(1))
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
                except Exception as e:
                    st.error(f"❌ JSON parsing error: {e}")
                    st.text_area("Extracted JSON", json_match.group(1), height=300)

with tab2:
    st.title("🤖 LLM-Powered SQL Query Generator")
    st.markdown("""
    Ask any question about the i2b2 schema. I’ll return:
    - A **SQL query**
    - Example **input/output**
    - A **R DBI-compatible call**
    - A simple **explanation**
    """)

    user_question = st.text_input("💬 What do you want to query?", key="user_request")

    if user_question:
        with st.spinner("Generating SQL and examples…"):
            prompt = f"""
You are a senior data engineer and educator with deep expertise in SQL, the i2b2 data model, and clinical informatics.

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
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            content = response.choices[0].message.content.strip()
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)

            if not json_match:
                st.error("❌ No valid JSON found in response.")
                st.text_area("Raw output:", content, height=300)
            else:
                try:
                    result = json.loads(json_match.group(1))
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
                except Exception as e:
                    st.error(f"❌ JSON parsing error: {e}")
                    st.text_area("Extracted JSON", json_match.group(1), height=300)
