import streamlit as st
import pandas as pd
import openai
import json
import re

st.set_page_config(page_title="Interactive Cohort Builder", layout="centered")

st.title("🧬 Interactive Cohort Builder (i2b2 schema)")

st.markdown("""
Build your own cohort/dataset by selecting columns & filters from the i2b2 schema.  
I'll generate:
- A **MySQL query**
- Example **input tables**
- Example **output table**
""")

# OpenAI API key
openai.api_key = st.secrets["OPENAI_API_KEY"]

# Define schema
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

st.markdown("### 📋 Step 1: Select tables")
selected_tables = st.multiselect(
    "Choose which tables to include in your cohort:", 
    list(schema.keys())
)

table_configs = {}

for table in selected_tables:
    st.markdown(f"### 🗃️ `{table}`")
    cols = st.multiselect(
        f"Columns to include from `{table}`:", 
        schema[table], 
        default=schema[table],
        key=f"cols_{table}"
    )
    filter_ = st.text_input(
        f"Optional filter condition on `{table}` (SQL WHERE fragment):", 
        key=f"filter_{table}"
    )
    table_configs[table] = {"columns": cols, "filter": filter_}

if st.button("🚀 Generate Query & Examples"):
    with st.spinner("Generating…"):
        # Compose natural language description
        desc = "I want to build a dataset with:\n"
        for table, cfg in table_configs.items():
            desc += f"- Table `{table}`: columns {cfg['columns']}"
            if cfg['filter']:
                desc += f", filtered by `{cfg['filter']}`"
            desc += "\n"

        prompt = f"""
You are a MySQL expert and teacher. Given the i2b2 database schema:

- observation_fact: encounter_num, patient_num, concept_cd, start_date
- patient_dimension: patient_num, birth_date, death_date, sex_cd, race_cd, ethnicity_cd, language_cd, marital_status_cd, zip_cd
- concept_dimension: concept_cd, name_char
- visit_dimension: encounter_id, patient_num, start_date, end_date

And the following user selection:\n{desc}

Write a MySQL query that joins the necessary tables, selects the specified columns and applies the filters.

Then generate a JSON with:
- sql: the MySQL query
- input_tables: example rows (dicts) per table
- output_table: example rows (dicts)

Return only valid JSON inside a markdown ```json block.
"""

        chat_completion = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        content = chat_completion.choices[0].message.content.strip()

        # Extract JSON block
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)

        if not json_match:
            st.error("Failed to find valid JSON in LLM response.")
            st.text_area("Raw response:", content, height=300)
            st.stop()

        json_str = json_match.group(1)

        try:
            result = json.loads(json_str)

            st.subheader("✅ Generated SQL Query:")
            st.code(result["sql"], language="sql")

            if result.get("input_tables"):
                st.markdown("### 📥 Example Input Tables")
                for table_name, rows in result["input_tables"].items():
                    df = pd.DataFrame(rows)
                    st.markdown(f"**`{table_name}`**")
                    st.dataframe(df)

            if result.get("output_table"):
                st.markdown("### 📤 Example Output Table")
                df_out = pd.DataFrame(result["output_table"])
                st.dataframe(df_out)

        except Exception as e:
            st.error(f"Failed to parse JSON: {e}")
            st.text_area("Extracted JSON:", json_str, height=300)
